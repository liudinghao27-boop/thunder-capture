"""Webhook push service for lead distribution."""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("thunder.webhook")


@dataclass
class WebhookPayload:
    industry_slug: str
    industry_name: str
    leads: list[dict[str, Any]]
    event: str = "leads.available"
    sent_at: str | None = None

    def __post_init__(self):
        if self.sent_at is None:
            self.sent_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


def push_leads_to_webhook(
    webhook_url: str,
    industry_slug: str,
    industry_name: str,
    leads: list[dict[str, Any]],
    timeout: float = 10.0,
) -> dict:
    """POST leads to external webhook URL. Returns result dict for logging."""
    if not webhook_url:
        return {"ok": False, "error": "webhook_url empty"}

    payload = WebhookPayload(
        industry_slug=industry_slug,
        industry_name=industry_name,
        leads=leads,
    )

    try:
        resp = httpx.post(
            webhook_url,
            content=payload.to_json(),
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        result = {
            "ok": 200 <= resp.status_code < 300,
            "status_code": resp.status_code,
            "response_preview": resp.text[:500],
        }
        if not result["ok"]:
            result["error"] = f"webhook returned {resp.status_code}"
        log.info("Webhook push to %s: %s", webhook_url, result)
        return result
    except Exception as e:
        log.warning("Webhook push failed: %s", e)
        return {"ok": False, "error": str(e)[:500]}
