"""Webhook push service for lead effect events."""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("thunder.effect_webhook")


def push_effect_event(
    event: str,
    industry_slug: str,
    lead: dict[str, Any],
    webhook_url: str,
    timeout: float = 10.0,
) -> dict:
    """Push lead.replied / lead.converted event to external webhook."""
    if not webhook_url:
        return {"ok": False, "error": "webhook_url empty"}

    payload = {
        "event": event,
        "industry_slug": industry_slug,
        "lead_id": lead.get("id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if event == "lead.replied":
        payload["reply_text"] = lead.get("reply_text", "")
    elif event == "lead.converted":
        payload["conversion_value"] = lead.get("conversion_value", "")

    try:
        resp = httpx.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        result = {
            "ok": 200 <= resp.status_code < 300,
            "status_code": resp.status_code,
            "response_preview": resp.text[:500],
        }
        log.info("Effect webhook push to %s: %s", webhook_url, result)
        return result
    except Exception as e:
        log.warning("Effect webhook push failed: %s", e)
        return {"ok": False, "error": str(e)[:500]}
