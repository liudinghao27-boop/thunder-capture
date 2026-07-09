import os
import shutil
import sys
import time
import socket
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def find_chrome_path() -> Optional[str]:
    candidates = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "msedge",
    ]
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found

    paths = []
    if sys.platform == "win32":
        paths.extend(
            [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            ]
        )
    elif sys.platform == "darwin":
        paths.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
        )
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        port = int(s.getsockname()[1])
    return port


class ShadowBrowser:
    # How long to wait for the Chrome debugging port to become reachable.
    STARTUP_TIMEOUT_SECONDS = 30

    def __init__(self, user_data_dir: str):
        self.port = find_free_port()
        self.user_data_dir = user_data_dir
        self.process: Optional[subprocess.Popen] = None
        self.chrome_path = find_chrome_path()

    def _chrome_version(self) -> str:
        """Return the major.minor.patch.build version of the found Chrome binary.

        ``chrome --version`` can hang on Windows because it launches a full
        browser process, so we read the executable's file-version metadata
        instead.
        """
        if not self.chrome_path:
            return ""
        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-Command",
                        f"(Get-ItemProperty '{self.chrome_path}').VersionInfo.ProductVersion",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                version = result.stdout.strip()
                if version:
                    return version
            else:
                result = subprocess.run(
                    [self.chrome_path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                parts = result.stdout.strip().split()
                if parts:
                    return parts[-1]
        except Exception as exc:
            logger.warning("[ShadowBrowser] Failed to detect Chrome version: %s", exc)
        return ""

    def _user_agent(self) -> str:
        """Build a User-Agent that matches the actual Chrome/Edge version.

        A mismatched User-Agent (e.g. hard-coded Chrome/125 against real
        Chrome/149) causes Douyin's a_bogus signature validation to fail and
        triggers login/risk-control responses.
        """
        version = self._chrome_version() or "125.0.0.0"
        return (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{version} Safari/537.36"
        )

    def start(self):
        if not self.chrome_path:
            raise RuntimeError(
                "Cannot find Chrome or Edge installation on this system."
            )

        # Ensure user data dir exists
        os.makedirs(self.user_data_dir, exist_ok=True)

        cmd = [
            self.chrome_path,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={os.path.abspath(self.user_data_dir)}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1280,720",
            # Anti-detection flags to reduce platform CAPTCHA triggers
            "--headless=new",
            "--disable-blink-features=AutomationControlled",
            "--exclude-switches=enable-automation",
            "--disable-infobars",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-features=IsolateOrigins,site-per-process",
            f"--user-agent={self._user_agent()}",
        ]

        # Route browser traffic through the same proxy pool used by MediaCrawler
        # HTTP requests. This helps bypass platform-level IP/risk control.
        proxy_url = os.environ.get("THUNDER_MEDIACRAWLER_PROXY_URL", "")
        if proxy_url:
            cmd.append(f"--proxy-server={proxy_url}")
            logger.info("[ShadowBrowser] Using proxy: %s", proxy_url)

        logger.info(
            "[ShadowBrowser] Starting Chrome on port %d (user_data_dir=%s)",
            self.port,
            self.user_data_dir,
        )
        logger.debug("[ShadowBrowser] Chrome command: %s", " ".join(cmd))

        popen_kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
        self.process = subprocess.Popen(cmd, **popen_kwargs)

        # Wait for the debugging port to become reachable. Chrome can take a
        # while on Windows when the user data dir is large or an update is
        # pending, so use a generous timeout and surface early exit as a
        # distinct error.
        start_time = time.time()
        elapsed = 0.0
        while elapsed < self.STARTUP_TIMEOUT_SECONDS:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"Chrome exited early (code={self.process.returncode}) "
                    f"while waiting for debugging port {self.port}"
                )
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                    logger.info(
                        "[ShadowBrowser] Chrome ready on port %d after %.1fs",
                        self.port,
                        elapsed,
                    )
                    return
            except OSError:
                time.sleep(0.5)
                elapsed = time.time() - start_time

        raise RuntimeError(
            f"Timeout waiting for ShadowBrowser debugging port {self.port} "
            f"after {self.STARTUP_TIMEOUT_SECONDS}s"
        )

    def close(self):
        if self.process:
            logger.info("Closing ShadowBrowser...")
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
            except Exception as e:
                logger.error(f"Failed to kill ShadowBrowser tree: {e}")
                self.process.terminate()

            self.process = None
            logger.info("ShadowBrowser closed.")
