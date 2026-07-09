from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
import time
import random
import asyncio
import httpx
from urllib.parse import urlparse, quote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class Proxy:
    def __init__(self, url: str, provider: str = "", expire_at: float = 0.0):
        self.url = url
        self.provider = provider
        self.expire_at = expire_at
        self.fail_count = 0
        self.last_used = 0.0
        self.last_check = 0.0
        self.latency_ms = 0.0

    def parsed(self) -> urlparse:
        return urlparse(self.url)

    def __repr__(self):
        return f"Proxy({self.provider}, {self.url[:30]}...)"


class ProviderAdapter:
    """Base class for proxy provider adapters."""

    def __init__(self, config: Dict):
        self.config = config

    async def fetch(self) -> List[Proxy]:
        raise NotImplementedError


class BrightDataAdapter(ProviderAdapter):
    """Bright Data residential proxy adapter.

    Bright Data residential proxy format:
      http://brd-customer-<CUSTOMER_ID>-zone-<ZONE>:<ZONE_PASSWORD>@brd.superproxy.io:22225
    With country and session targeting:
      http://brd-customer-<CUSTOMER_ID>-zone-<ZONE>:<ZONE_PASSWORD>@brd.superproxy.io:22225
      -country-<CC>-session-<SESSION>
    """

    async def fetch(self) -> List[Proxy]:
        customer_id = self.config.get("customer_id", "")
        zone = self.config.get("zone", "residential")
        password = self.config.get("zone_password", "")
        country = self.config.get("country", "")
        session_id = self.config.get("session_id", "")
        if not customer_id or not password:
            raise ValueError("BrightData: customer_id and zone_password are required")

        host = "brd.superproxy.io"
        port = 22225
        user = f"brd-customer-{customer_id}-zone-{zone}"
        if country:
            user += f"-country-{country}"
        if session_id:
            user += f"-session-{session_id}"

        proxy_url = f"http://{user}:{password}@{host}:{port}"
        # For a single session, return one proxy. If you need multiple sessions,
        # append random suffixes to session_id.
        return [Proxy(proxy_url, provider="brightdata", expire_at=time.time() + 3600)]


class OxylabsAdapter(ProviderAdapter):
    """Oxylabs residential proxy adapter.

    Oxylabs proxy format:
      http://<USERNAME>:<PASSWORD>@pr.oxylabs.io:7777
    With country targeting:
      http://<USERNAME>-cc-<CC>-sessid-<SESSID>:<PASSWORD>@pr.oxylabs.io:7777
    """

    async def fetch(self) -> List[Proxy]:
        username = self.config.get("username", "")
        password = self.config.get("password", "")
        country = self.config.get("country", "")
        session_id = self.config.get("session_id", "")
        if not username or not password:
            raise ValueError("Oxylabs: username and password are required")

        user = username
        if country:
            user += f"-cc-{country}"
        if session_id:
            user += f"-sessid-{session_id}"

        proxy_url = f"http://{user}:{password}@pr.oxylabs.io:7777"
        return [Proxy(proxy_url, provider="oxylabs", expire_at=time.time() + 3600)]


class StaticAdapter(ProviderAdapter):
    """Static proxy URL adapter (e.g. local Clash/V2Ray outbound)."""

    async def fetch(self) -> List[Proxy]:
        url = self.config.get("proxy_url", "")
        if not url:
            raise ValueError("Static: proxy_url is required")
        return [Proxy(url, provider="static", expire_at=time.time() + 86400)]


ADAPTER_MAP = {
    "brightdata": BrightDataAdapter,
    "oxylabs": OxylabsAdapter,
    "static": StaticAdapter,
}


class ProxyPool:
    def __init__(self, config_path: Path = Path("docs/qa/proxy_pool_config.json")):
        self.config_path = config_path
        self.config: Dict = json.loads(config_path.read_text(encoding="utf-8"))
        self.proxies: List[Proxy] = []
        self._lock = asyncio.Lock()
        self._last_fetch = 0.0

    def _build_adapter(self, provider: Dict) -> ProviderAdapter:
        ptype = provider.get("type", provider.get("name", ""))
        adapter_cls = ADAPTER_MAP.get(ptype)
        if not adapter_cls:
            raise ValueError(f"Unknown proxy provider type: {ptype}")
        return adapter_cls(provider)

    async def fetch_from_providers(self) -> int:
        """Fetch fresh proxies from configured providers."""
        new_count = 0
        for provider in self.config.get("providers", []):
            if not provider.get("enabled"):
                logger.info("Provider %s disabled, skip", provider.get("name"))
                continue
            try:
                adapter = self._build_adapter(provider)
                fetched = await adapter.fetch()
                async with self._lock:
                    for p in fetched:
                        if not self._has_proxy(p):
                            self.proxies.append(p)
                            new_count += 1
                            logger.info("Added proxy from %s", p.provider)
                if fetched:
                    self._last_fetch = time.time()
            except Exception as e:
                logger.warning("Failed to fetch from %s: %s", provider.get("name"), e)
        return new_count

    def _has_proxy(self, proxy: Proxy) -> bool:
        return any(p.url == proxy.url for p in self.proxies)

    async def get_proxy(self) -> Optional[Proxy]:
        async with self._lock:
            now = time.time()
            # Remove expired or too-failed proxies
            before = len(self.proxies)
            self.proxies = [
                p for p in self.proxies
                if p.expire_at > now and p.fail_count < self.config["health_check"]["max_failures_before_remove"]
            ]
            removed = before - len(self.proxies)
            if removed:
                logger.info("Removed %s expired/failed proxies", removed)
            if not self.proxies:
                return None
            # Pick least recently used
            p = min(self.proxies, key=lambda x: x.last_used)
            p.last_used = now
            return p

    async def mark_failed(self, proxy: Proxy):
        async with self._lock:
            for p in self.proxies:
                if p.url == proxy.url:
                    p.fail_count += 1
                    break

    async def health_check(self) -> Tuple[int, int]:
        """Run health check on all proxies. Returns (ok_count, fail_count)."""
        target = self.config["health_check"]["target_url"]
        timeout = self.config["health_check"]["timeout_seconds"]
        ok = 0
        fail = 0

        async with self._lock:
            proxies = list(self.proxies)

        for p in proxies:
            start = time.time()
            try:
                async with httpx.AsyncClient(proxies=p.url, timeout=timeout, follow_redirects=True) as client:
                    r = await client.get(target)
                    if r.status_code < 500:
                        p.latency_ms = (time.time() - start) * 1000
                        p.last_check = time.time()
                        ok += 1
                    else:
                        fail += 1
                        await self.mark_failed(p)
            except Exception as e:
                logger.debug("Health check failed for %s: %s", p.provider, e)
                fail += 1
                await self.mark_failed(p)
        return ok, fail

    def request_interval(self) -> float:
        interval = self.config.get("request_interval", {})
        return random.uniform(interval.get("min_seconds", 1), interval.get("max_seconds", 5))


class ProxyPoolServer:
    """Lightweight HTTP proxy that forwards requests through a rotating residential proxy."""

    def __init__(self, host: str, port: int, pool: ProxyPool):
        self.host = host
        self.port = port
        self.pool = pool
        self.server = None

    def start(self):
        pool = self.pool

        class Handler(BaseHTTPRequestHandler):
            def _forward(self, method: str):
                asyncio.run(self._do_proxy(method))

            async def _do_proxy(self, method: str):
                proxy = await pool.get_proxy()
                if not proxy:
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(b"No proxy available")
                    return

                # Add random delay before forwarding to reduce rate-limit risk.
                await asyncio.sleep(pool.request_interval())

                try:
                    async with httpx.AsyncClient(proxies=proxy.url, timeout=30, follow_redirects=True) as client:
                        if method == "GET":
                            r = await client.get(self.path)
                        elif method == "POST":
                            length = int(self.headers.get('Content-Length', 0))
                            body = self.rfile.read(length)
                            r = await client.post(self.path, content=body)
                        else:
                            r = await client.request(method, self.path)

                        self.send_response(r.status_code)
                        for k, v in r.headers.items():
                            if k.lower() not in ("transfer-encoding", "content-encoding"):
                                self.send_header(k, v)
                        self.end_headers()
                        self.wfile.write(r.content)
                        logger.info("Forwarded %s via %s status=%s", method, proxy.provider, r.status_code)
                except Exception as e:
                    await pool.mark_failed(proxy)
                    self.send_response(502)
                    self.end_headers()
                    self.wfile.write(str(e).encode())
                    logger.warning("Proxy failed via %s: %s", proxy.provider, e)

            def do_GET(self):
                self._forward("GET")

            def do_POST(self):
                self._forward("POST")

            def do_CONNECT(self):
                self.send_response(501)
                self.end_headers()
                self.wfile.write(b"CONNECT not supported")

            def log_message(self, fmt, *args):
                pass

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        Thread(target=self.server.serve_forever, daemon=True).start()
        logger.info("Proxy pool server started at http://%s:%s", self.host, self.port)

    def stop(self):
        if self.server:
            self.server.shutdown()


async def main():
    pool = ProxyPool()
    await pool.fetch_from_providers()
    if not pool.proxies:
        logger.warning("No residential proxies configured. Add provider credentials to proxy_pool_config.json.")
    else:
        logger.info("Loaded %s proxies.", len(pool.proxies))
        ok, fail = await pool.health_check()
        logger.info("Health check: %s OK, %s failed", ok, fail)

    cfg = pool.config["local_pool_server"]
    server = ProxyPoolServer(cfg["host"], cfg["port"], pool)
    server.start()

    try:
        while True:
            await asyncio.sleep(pool.config["health_check"]["interval_seconds"])
            await pool.fetch_from_providers()
            ok, fail = await pool.health_check()
            logger.info("Pool: %s proxies, health %s/%s", len(pool.proxies), ok, ok + fail)
    except KeyboardInterrupt:
        logger.info("Shutting down proxy pool server...")
        server.stop()


if __name__ == "__main__":
    asyncio.run(main())
