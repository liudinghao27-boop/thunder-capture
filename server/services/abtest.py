"""A/B test helpers for reply variants."""

from __future__ import annotations

import random
import uuid
from typing import Any


def generate_variant_id() -> str:
    return f"v-{uuid.uuid4().hex[:8]}"


def validate_variant(variant: dict[str, Any]) -> bool:
    """Check that a variant has the minimum required fields."""
    if not isinstance(variant, dict):
        return False
    if not variant.get("id") or not variant.get("name"):
        return False
    return True


def _to_weight(value: Any) -> int | float:
    """Coerce a value to a non-negative numeric weight."""
    try:
        weight = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    if weight != weight:  # NaN check
        return 0
    return max(0, weight)


def normalize_variant(variant: dict[str, Any]) -> dict[str, Any]:
    """Ensure a variant has all standard fields and a valid id.

    Works on a shallow copy so the caller's dict is not mutated.
    """
    normalized = dict(variant)
    if not normalized.get("id"):
        normalized["id"] = generate_variant_id()
    normalized.setdefault("name", "未命名")
    normalized.setdefault("reply_tone", "")
    normalized.setdefault("reply_style", "")
    normalized.setdefault("reply_hook", "")
    normalized.setdefault("weight", 1)
    normalized.setdefault("enabled", True)
    return normalized


def select_reply_variant(
    variants: list[dict[str, Any]] | None,
    rng: Any = random,
) -> dict[str, Any] | None:
    """Weighted random selection of an enabled, valid reply variant.

    Invalid variants (including ``None`` items and dicts missing required
    fields) are skipped. ``rng`` may be swapped out for deterministic tests.
    """
    if not variants:
        return None
    enabled = [
        normalize_variant(v)
        for v in variants
        if v is not None and v.get("enabled", True) and validate_variant(v)
    ]
    if not enabled:
        return None
    total_weight = sum(_to_weight(v.get("weight", 1)) for v in enabled)
    if total_weight <= 0:
        return enabled[0]
    r = rng.uniform(0, total_weight)
    cumulative = 0.0
    for v in enabled:
        cumulative += _to_weight(v.get("weight", 1))
        if r <= cumulative:
            return v
    return enabled[-1]


def build_variant_result(variant_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate sent/replied/converted for a variant from TaskQueue-like rows."""
    sent = sum(
        1 for r in rows if r.get("status") in ("sent", "replied", "converted", "done")
    )
    replied = sum(1 for r in rows if r.get("status") in ("replied", "converted"))
    converted = sum(1 for r in rows if r.get("status") == "converted")
    reply_rate = round(replied / sent, 4) if sent else 0.0
    conversion_rate = round(converted / sent, 4) if sent else 0.0
    return {
        "id": variant_id,
        "sent": sent,
        "replied": replied,
        "converted": converted,
        "reply_rate": reply_rate,
        "conversion_rate": conversion_rate,
    }


def pick_winner(
    results: list[dict[str, Any]], metric: str = "reply_rate"
) -> str | None:
    """Return the variant id with the highest metric, or None if empty.

    On ties, ``max`` returns the first item with the highest value.
    """
    if not results:
        return None
    best = max(results, key=lambda r: r.get(metric, 0))
    return best.get("id")
