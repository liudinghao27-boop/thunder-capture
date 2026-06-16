
from server.services.abtest import (
    build_variant_result,
    generate_variant_id,
    normalize_variant,
    pick_winner,
    select_reply_variant,
    validate_variant,
)


class DeterministicRNG:
    """Test double that always returns a fixed sequence of uniforms."""

    def __init__(self, values):
        self._values = list(values)
        self._index = 0

    def uniform(self, a, b):
        value = self._values[self._index % len(self._values)]
        self._index += 1
        return a + value * (b - a)


def test_select_variant_returns_one():
    variants = [
        {"id": "v1", "name": "A", "weight": 1, "enabled": True},
        {"id": "v2", "name": "B", "weight": 1, "enabled": True},
    ]
    v = select_reply_variant(variants)
    assert v["id"] in ("v1", "v2")


def test_select_variant_respects_weight():
    variants = [
        {"id": "v1", "name": "A", "weight": 0, "enabled": True},
        {"id": "v2", "name": "B", "weight": 1, "enabled": True},
    ]
    for _ in range(10):
        v = select_reply_variant(variants)
        assert v["id"] == "v2"


def test_select_variant_skips_disabled():
    variants = [
        {"id": "v1", "name": "A", "weight": 1, "enabled": False},
        {"id": "v2", "name": "B", "weight": 1, "enabled": True},
    ]
    v = select_reply_variant(variants)
    assert v["id"] == "v2"


def test_select_variant_skips_invalid_and_none():
    variants = [
        None,
        {"name": "no-id"},
        {"id": "v1", "name": "A", "weight": 1, "enabled": True},
    ]
    for _ in range(10):
        v = select_reply_variant(variants)
        assert v["id"] == "v1"


def test_select_variant_non_numeric_weight_treated_as_zero():
    variants = [
        {"id": "v1", "name": "A", "weight": "heavy", "enabled": True},
        {"id": "v2", "name": "B", "weight": 1, "enabled": True},
    ]
    for _ in range(10):
        v = select_reply_variant(variants)
        assert v["id"] == "v2"


def test_select_variant_negative_weight_treated_as_zero():
    variants = [
        {"id": "v1", "name": "A", "weight": -5, "enabled": True},
        {"id": "v2", "name": "B", "weight": 1, "enabled": True},
    ]
    for _ in range(10):
        v = select_reply_variant(variants)
        assert v["id"] == "v2"


def test_select_variant_uses_injected_rng():
    variants = [
        {"id": "v1", "name": "A", "weight": 1, "enabled": True},
        {"id": "v2", "name": "B", "weight": 1, "enabled": True},
    ]
    rng = DeterministicRNG([0.0])
    v = select_reply_variant(variants, rng=rng)
    assert v["id"] == "v1"

    rng = DeterministicRNG([0.99])
    v = select_reply_variant(variants, rng=rng)
    assert v["id"] == "v2"


def test_select_variant_empty_list_returns_none():
    assert select_reply_variant([]) is None
    assert select_reply_variant(None) is None


def test_validate_variant_requires_id_and_name():
    assert validate_variant({"name": "A"}) is False
    assert validate_variant({"id": "v1", "name": "A"}) is True


def test_validate_variant_rejects_non_dict():
    assert validate_variant(None) is False
    assert validate_variant("variant") is False
    assert validate_variant(["id", "v1"]) is False


def test_normalize_variant_fills_defaults_and_generates_id():
    original = {}
    normalized = normalize_variant(original)
    assert normalized["id"].startswith("v-")
    assert normalized["name"] == "未命名"
    assert normalized["reply_tone"] == ""
    assert normalized["reply_style"] == ""
    assert normalized["reply_hook"] == ""
    assert normalized["weight"] == 1
    assert normalized["enabled"] is True


def test_normalize_variant_preserves_existing_values():
    original = {
        "id": "v1",
        "name": "A",
        "reply_tone": "friendly",
        "reply_style": "short",
        "reply_hook": "ask",
        "weight": 3,
        "enabled": False,
    }
    normalized = normalize_variant(original)
    assert normalized == original


def test_normalize_variant_does_not_mutate_input():
    original = {"name": "A"}
    normalized = normalize_variant(original)
    assert original == {"name": "A"}
    assert "id" in normalized


def test_build_variant_result_empty():
    result = build_variant_result("v1", [])
    assert result["id"] == "v1"
    assert result["sent"] == 0
    assert result["reply_rate"] == 0.0
    assert result["conversion_rate"] == 0.0


def test_build_variant_result_aggregates_rows():
    rows = [
        {"status": "sent"},
        {"status": "replied"},
        {"status": "converted"},
        {"status": "pending"},
    ]
    result = build_variant_result("v1", rows)
    assert result["sent"] == 3
    assert result["replied"] == 2
    assert result["converted"] == 1
    assert result["reply_rate"] == round(2 / 3, 4)
    assert result["conversion_rate"] == round(1 / 3, 4)


def test_generate_variant_id_format():
    vid = generate_variant_id()
    assert isinstance(vid, str)
    assert vid.startswith("v-")
    assert len(vid) == 10


def test_pick_winner_returns_best_variant():
    results = [
        {"id": "v1", "reply_rate": 0.1},
        {"id": "v2", "reply_rate": 0.5},
    ]
    assert pick_winner(results) == "v2"


def test_pick_winner_first_wins_on_tie():
    results = [
        {"id": "v1", "reply_rate": 0.5},
        {"id": "v2", "reply_rate": 0.5},
    ]
    assert pick_winner(results) == "v1"


def test_pick_winner_empty_returns_none():
    assert pick_winner([]) is None


def test_pick_winner_custom_metric():
    results = [
        {"id": "v1", "reply_rate": 0.9, "conversion_rate": 0.1},
        {"id": "v2", "reply_rate": 0.1, "conversion_rate": 0.9},
    ]
    assert pick_winner(results, metric="conversion_rate") == "v2"
