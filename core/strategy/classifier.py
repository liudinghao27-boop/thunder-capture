"""Classifier facade — delegates to engine.classify for LLM intent classification.

Provides a strategy-layer entry point for the intent classification pipeline,
keeping the classify module accessible through the strategy namespace.
"""

from __future__ import annotations

from core.classify import (
    classify_batch,
    enqueue_classified,
    prefilter_comments,
)
from core.config import IndustryConfig

__all__ = [
    "classify_batch",
    "enqueue_classified",
    "prefilter_comments",
    "IndustryConfig",
]
