"""ProxyRotator — 代理轮换器，参考 Scrapling 设计"""

import logging
import threading
from typing import Callable

log = logging.getLogger("thunder.proxy")

# 代理错误的特征字符串
_PROXY_ERROR_INDICATORS = {
    "net::err_proxy",
    "net::err_tunnel",
    "connection refused",
    "connection reset",
    "connection timed out",
    "failed to connect",
    "could not resolve proxy",
    "proxy",
    "tunnel",
    "socks",
}

RotationStrategy = Callable[[list[str], int], tuple[str, int]]


def is_proxy_error(error: str) -> bool:
    """检查错误是否与代理相关"""
    error_lower = error.lower()
    return any(indicator in error_lower for indicator in _PROXY_ERROR_INDICATORS)


def cyclic_rotation(proxies: list[str], current_index: int) -> tuple[str, int]:
    """默认循环轮换策略"""
    idx = current_index % len(proxies)
    return proxies[idx], (idx + 1) % len(proxies)


class ProxyRotator:
    """线程安全的代理轮换器，支持自定义轮换策略。

    使用示例:
        rotator = ProxyRotator(["http://p1:8080", "http://p2:8080"])
        proxy = rotator.get_proxy()
        ...
        if failed and is_proxy_error(error_msg):
            proxy = rotator.get_proxy()  # 自动轮换到下一个
    """

    __slots__ = ("_proxies", "_strategy", "_current_index", "_lock")

    def __init__(
        self,
        proxies: list[str],
        strategy: RotationStrategy = cyclic_rotation,
    ):
        if not proxies:
            raise ValueError("至少需要提供一个代理地址")
        if not callable(strategy):
            raise TypeError(f"strategy 必须是 callable，收到 {type(strategy)}")

        self._proxies = proxies
        self._strategy = strategy
        self._current_index = 0
        self._lock = threading.Lock()

    def get_proxy(self) -> str:
        """获取下一个代理（线程安全）"""
        with self._lock:
            proxy, self._current_index = self._strategy(
                self._proxies, self._current_index
            )
            log.debug(f"代理轮换: {proxy[:40]}... (index={self._current_index})")
            return proxy

    @property
    def proxies(self) -> list[str]:
        """返回代理列表副本"""
        return list(self._proxies)

    def __len__(self) -> int:
        return len(self._proxies)

    def __repr__(self) -> str:
        return f"ProxyRotator(proxies={len(self._proxies)})"
