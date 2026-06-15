"""Android UI hierarchy parsing and screen-state inference."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from core.device.adb_client import ADBClient


@dataclass(frozen=True)
class UIElement:
    text: str = ""
    resource_id: str = ""
    class_name: str = ""
    content_desc: str = ""
    bounds: str = ""
    clickable: bool = False
    enabled: bool = True
    focused: bool = False

    def label(self) -> str:
        return self.text or self.content_desc or self.resource_id or self.class_name

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "resource_id": self.resource_id,
            "class_name": self.class_name,
            "content_desc": self.content_desc,
            "bounds": self.bounds,
            "clickable": self.clickable,
            "enabled": self.enabled,
            "focused": self.focused,
        }


@dataclass(frozen=True)
class ScreenState:
    screen: str
    confidence: float = 0.0
    blocker: str = ""
    evidence: list[str] = field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return bool(self.blocker)

    def as_dict(self) -> dict[str, Any]:
        return {
            "screen": self.screen,
            "confidence": round(float(self.confidence), 3),
            "blocker": self.blocker,
            "evidence": self.evidence,
        }


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _score(match_count: int, total: int, base: float = 0.2) -> float:
    if total <= 0:
        return 0.0
    return min(0.99, base + (match_count / total) * (1.0 - base))


class UIParser:
    def dump_xml(self, serial: str) -> str:
        client = ADBClient(serial)
        client.shell("uiautomator", "dump", "/sdcard/window_dump.xml", timeout=8, check=True)
        result = client.shell("cat", "/sdcard/window_dump.xml", timeout=8, check=True)
        return result.stdout

    def parse(self, xml_text: str) -> list[UIElement]:
        elements: list[UIElement] = []
        if not xml_text:
            return elements
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return elements
        for node in root.iter("node"):
            elements.append(
                UIElement(
                    text=node.attrib.get("text", ""),
                    resource_id=node.attrib.get("resource-id", ""),
                    class_name=node.attrib.get("class", ""),
                    content_desc=node.attrib.get("content-desc", ""),
                    bounds=node.attrib.get("bounds", ""),
                    clickable=node.attrib.get("clickable", "false") == "true",
                    enabled=node.attrib.get("enabled", "true") == "true",
                    focused=node.attrib.get("focused", "false") == "true",
                )
            )
        return elements

    def infer_screen(
        self,
        elements: list[UIElement],
        *,
        ocr_text: str = "",
        package_name: str = "",
        activity: str = "",
    ) -> ScreenState:
        labels = " ".join(e.label() for e in elements if e.label())
        text = " ".join([labels, ocr_text or "", package_name or "", activity or ""])
        evidence: list[str] = []

        blocker = self._infer_blocker(text)
        if blocker:
            return ScreenState("blocked", 0.98, blocker=blocker, evidence=[blocker])

        rules: list[tuple[str, list[str], list[str]]] = [
            (
                "message_sent",
                [r"刚刚", r"已发送", r"发送成功", r"消息已送达", r"sent"],
                ["message/send evidence"],
            ),
            (
                "chat",
                [r"私信", r"聊天", r"发送", r"输入消息", r"说点什么", r"EditText", r"message"],
                ["chat/input controls"],
            ),
            (
                "profile",
                [r"关注", r"粉丝", r"获赞", r"作品", r"私信", r"主页"],
                ["profile controls"],
            ),
            (
                "search",
                [r"搜索", r"用户", r"综合", r"视频", r"search"],
                ["search controls"],
            ),
            (
                "home",
                [r"首页", r"朋友", r"消息", r"我", r"推荐", r"关注"],
                ["home tabs"],
            ),
            (
                "loading",
                [r"加载中", r"正在加载", r"请稍候", r"loading"],
                ["loading text"],
            ),
            (
                "not_found",
                [r"用户不存在", r"搜索无结果", r"暂无相关结果", r"not found"],
                ["not found text"],
            ),
            (
                "dm_unavailable",
                [r"对方设置了隐私", r"不能发私信", r"无法发送", r"消息发送失败"],
                ["dm unavailable text"],
            ),
        ]

        best = ScreenState("unknown", 0.0, evidence=[])
        for screen, patterns, hints in rules:
            matched = [pattern for pattern in patterns if _has(text, pattern)]
            if not matched:
                continue
            confidence = _score(len(matched), len(patterns))
            if confidence > best.confidence:
                evidence = [*hints, *matched[:4]]
                best = ScreenState(screen, confidence, evidence=evidence)

        if best.screen == "unknown" and package_name:
            evidence = [f"package={package_name}"]
            if activity:
                evidence.append(f"activity={activity}")
            return ScreenState("unknown", 0.25, evidence=evidence)
        return best

    def _infer_blocker(self, text: str) -> str:
        blockers = [
            ("real_name_verification", [r"实名认证", r"身份认证", r"刷脸", r"人脸识别"]),
            ("captcha", [r"验证码", r"安全验证", r"拖动滑块", r"验证"]),
            ("login_required", [r"登录", r"注册", r"手机号登录", r"获取验证码"]),
            ("risk_control", [r"操作频繁", r"账号异常", r"风控", r"暂时无法", r"限制"]),
            ("permission_dialog", [r"允许", r"权限", r"始终允许", r"仅使用期间允许"]),
            ("teen_mode", [r"青少年模式"]),
        ]
        for name, patterns in blockers:
            if any(_has(text, pattern) for pattern in patterns):
                return name
        return ""


def observe_ui(serial: str) -> dict:
    parser = UIParser()
    xml = parser.dump_xml(serial)
    elements = parser.parse(xml)
    state = parser.infer_screen(elements)
    return {
        **state.as_dict(),
        "elements": [e.as_dict() for e in elements[:200]],
        "element_count": len(elements),
    }
