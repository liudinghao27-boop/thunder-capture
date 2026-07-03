"""Shared default constants for Thunder Capture.

These values are used as fallbacks when a user or industry config does not
override them. Centralizing them makes it easier to tune the system and keep
schema/model/code defaults consistent.
"""

# ── Sending defaults ──
DEFAULT_DAILY_LIMIT = 15
DEFAULT_MIN_INTERVAL_SEC = 90

# ── Matrix / replenishment defaults ──
DEFAULT_MATRIX_TARGET_DEVICES = 30
DEFAULT_LEAD_INVENTORY_DAYS = 3
DEFAULT_REPLENISH_THRESHOLD_DAYS = 1

# ── Collection defaults ──
DEFAULT_VIDEO_MAX_AGE_DAYS = 14
DEFAULT_COMMENT_MAX_AGE_HOURS = 48
DEFAULT_KEYWORD_BATCH_SIZE = 12
DEFAULT_COLLECT_AUTHORS_PER_RUN = 60
DEFAULT_COLLECT_VIDEO_LIMIT = 120

# ── Agent defaults ──
DEFAULT_AGENT_MAX_STEPS = 20
