"""SessionManager — 浏览器会话池，参考 Scrapling 设计

允许多个采集器共享浏览器实例，减少资源消耗。
"""

import logging
import threading
from typing import Optional

log = logging.getLogger("thunder.session")

Session = object  # forward reference


class SessionManager:
    """管理预配置的浏览器会话实例。

    使用示例:
        manager = SessionManager()
        manager.add("douyin", DouyinSession(profile_dir=...), default=True)
        async with manager:
            session = manager.get("douyin")
            await session.fetch(...)
    """

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._default_session_id: Optional[str] = None
        self._started: bool = False
        self._lazy_sessions: set[str] = set()
        self._lazy_lock = threading.Lock()

    def add(
        self,
        session_id: str,
        session: Session,
        *,
        default: bool = False,
        lazy: bool = False,
    ) -> "SessionManager":
        """注册一个会话实例。

        :param session_id: 会话名称
        :param session: 预配置的会话实例
        :param default: 设为默认会话
        :param lazy: 延迟启动 — 仅在首次使用时启动
        """
        if session_id in self._sessions:
            raise ValueError(f"Session '{session_id}' 已注册")

        self._sessions[session_id] = session

        if default or self._default_session_id is None:
            self._default_session_id = session_id

        if lazy:
            self._lazy_sessions.add(session_id)

        return self

    def remove(self, session_id: str) -> None:
        """移除并关闭一个会话"""
        session = self._sessions.pop(session_id, None)
        if session is None:
            raise KeyError(f"Session '{session_id}' 未找到")

        self._lazy_sessions.discard(session_id)

        if session_id == self._default_session_id:
            self._default_session_id = next(iter(self._sessions), None)

    def get(self, session_id: str) -> Session:
        """获取指定会话"""
        if session_id not in self._sessions:
            available = ", ".join(self._sessions.keys())
            raise KeyError(f"Session '{session_id}' 未找到。可用: {available}")
        return self._sessions[session_id]

    @property
    def default_session_id(self) -> str:
        if self._default_session_id is None:
            raise RuntimeError("未注册任何会话")
        return self._default_session_id

    @property
    def session_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._sessions

    def __len__(self) -> int:
        return len(self._sessions)

    def __repr__(self) -> str:
        ids = ", ".join(self._sessions.keys())
        return f"SessionManager(sessions=[{ids}])"
