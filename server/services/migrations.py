"""Database initialization and additive schema migrations."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

log = logging.getLogger("thunder.migrations")

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    ddl: str


ADDITIVE_MIGRATIONS: dict[str, tuple[ColumnSpec, ...]] = {
    "sa_users": (
        ColumnSpec("deepseek_key", "VARCHAR(128) DEFAULT ''"),
        ColumnSpec("zhipu_key", "VARCHAR(128) DEFAULT ''"),
        ColumnSpec("openai_key", "VARCHAR(128) DEFAULT ''"),
    ),
    "sa_industries": (
        ColumnSpec("reply_hook", "VARCHAR(256) DEFAULT ''"),
        ColumnSpec("intent_keywords", "JSON DEFAULT '[]'"),
        ColumnSpec("noise_keywords", "JSON DEFAULT '[]'"),
        ColumnSpec("target_users", "JSON DEFAULT '[]'"),
        ColumnSpec("matrix_target_devices", "INTEGER DEFAULT 30"),
        ColumnSpec("lead_inventory_days", "INTEGER DEFAULT 3"),
        ColumnSpec("global_daily_limit", "INTEGER DEFAULT 0"),
        ColumnSpec("auto_replenish_enabled", "BOOLEAN DEFAULT FALSE"),
        ColumnSpec("replenish_threshold_days", "INTEGER DEFAULT 1"),
        ColumnSpec("keyword_batch_size", "INTEGER DEFAULT 12"),
        ColumnSpec("collect_authors_per_run", "INTEGER DEFAULT 60"),
        ColumnSpec("collect_video_limit", "INTEGER DEFAULT 120"),
        ColumnSpec("compliance_mode", "BOOLEAN DEFAULT FALSE"),
        ColumnSpec("webhook_url", "VARCHAR(512) DEFAULT ''"),
        ColumnSpec("auto_export_enabled", "BOOLEAN DEFAULT FALSE"),
        ColumnSpec("send_start_time", "VARCHAR(8) DEFAULT '09:00'"),
        ColumnSpec("send_end_time", "VARCHAR(8) DEFAULT '13:00'"),
        ColumnSpec("pause_weekends", "BOOLEAN DEFAULT FALSE"),
        ColumnSpec("daily_send_max", "INTEGER DEFAULT 0"),
        ColumnSpec("hourly_send_limit", "INTEGER DEFAULT 0"),
        ColumnSpec("effect_webhook_url", "VARCHAR(512) DEFAULT ''"),
        ColumnSpec("reply_variants", "JSON DEFAULT '[]'"),
    ),
    "sa_devices": (
        ColumnSpec("runtime_status", "VARCHAR(32) DEFAULT 'idle'"),
        ColumnSpec("consecutive_failures", "INTEGER DEFAULT 0"),
        ColumnSpec("last_error", "VARCHAR(500) DEFAULT ''"),
        ColumnSpec("last_started_at", "TIMESTAMP"),
        ColumnSpec("last_finished_at", "TIMESTAMP"),
        ColumnSpec("last_checked_at", "TIMESTAMP"),
        ColumnSpec("keyboard_ready", "BOOLEAN DEFAULT FALSE"),
        ColumnSpec("keyboard_message", "VARCHAR(256) DEFAULT ''"),
        ColumnSpec("health_score", "INTEGER DEFAULT 100"),
        ColumnSpec("cooldown_until", "TIMESTAMP"),
        ColumnSpec("last_job_id", "VARCHAR(36) DEFAULT ''"),
    ),
    "sa_jobs": (
        ColumnSpec("industry_slug", "VARCHAR(64) DEFAULT ''"),
        ColumnSpec("industry_name", "VARCHAR(128) DEFAULT ''"),
        ColumnSpec("payload", "JSON DEFAULT '{}'"),
        ColumnSpec("error", "VARCHAR(1000) DEFAULT ''"),
        ColumnSpec("cancel_requested", "BOOLEAN DEFAULT FALSE"),
        ColumnSpec("updated_at", "TIMESTAMP"),
        ColumnSpec("completed_at", "TIMESTAMP"),
    ),
    "sa_screen_snapshots": (
        ColumnSpec("task_id", "VARCHAR(36) DEFAULT ''"),
        ColumnSpec("stage", "VARCHAR(32) DEFAULT ''"),
        ColumnSpec("screen_name", "VARCHAR(128) DEFAULT ''"),
        ColumnSpec("blocker", "VARCHAR(64) DEFAULT ''"),
        ColumnSpec("image_path", "VARCHAR(512) DEFAULT ''"),
        ColumnSpec("ocr_text", "TEXT DEFAULT ''"),
        ColumnSpec("ui_tree", "JSON DEFAULT '{}'"),
        ColumnSpec("confidence", "INTEGER DEFAULT 0"),
        ColumnSpec("captured_at", "TIMESTAMP"),
        ColumnSpec("created_at", "TIMESTAMP"),
    ),
    "sa_target_bloggers": (ColumnSpec("owner_user_id", "VARCHAR(64) DEFAULT ''"),),
    "sa_industry_daily_quota": (ColumnSpec("owner_user_id", "VARCHAR(64) DEFAULT ''"),),
    "sa_collected_videos": (ColumnSpec("owner_user_id", "VARCHAR(64) DEFAULT ''"),),
    "sa_collector_state": (ColumnSpec("owner_user_id", "VARCHAR(64) DEFAULT ''"),),
}


def _assert_safe_identifier(value: str) -> None:
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")


def _existing_columns(engine: Engine, table_name: str) -> set[str]:
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def _add_missing_columns(engine: Engine) -> list[str]:
    added: list[str] = []
    with engine.begin() as conn:
        for table_name, columns in ADDITIVE_MIGRATIONS.items():
            _assert_safe_identifier(table_name)
            existing = _existing_columns(engine, table_name)
            if not existing:
                continue
            for column in columns:
                _assert_safe_identifier(column.name)
                if column.name in existing:
                    continue
                conn.execute(
                    text(
                        f"ALTER TABLE {table_name} ADD COLUMN {column.name} {column.ddl}"
                    )
                )
                added.append(f"{table_name}.{column.name}")
                existing.add(column.name)
    return added


def _backfill_owner_user_id(engine: Engine) -> list[str]:
    """Backfill owner_user_id for tables that gained the column.

    Existing rows without an owner are attributed to the user that owns the
    industry with the matching slug. Rows whose industry_slug is shared by
    multiple users are intentionally skipped and logged so an admin can
    reconcile them manually.

    For sa_collected_videos, the owner is inferred from TaskQueue.video_id
    matching CollectedVideo.aweme_id. Aweme IDs mapped to multiple owners are
    skipped as ambiguous.
    """
    updated: list[str] = []
    with Session(engine) as session:
        ambiguous_industries = {
            row[0]
            for row in session.execute(
                text(
                    """
                    SELECT slug FROM sa_industries
                    GROUP BY slug
                    HAVING COUNT(DISTINCT user_id) > 1
                    """
                )
            )
        }
        if ambiguous_industries:
            log.warning(
                "Skipping backfill for ambiguous slugs shared by multiple users: %s",
                sorted(ambiguous_industries),
            )

        tables = [
            ("sa_task_queue", "industry_slug"),
            ("sa_target_bloggers", "industry_slug"),
            ("sa_industry_daily_quota", "industry_slug"),
            ("sa_collector_state", "industry_slug"),
        ]
        for table_name, slug_column in tables:
            _assert_safe_identifier(table_name)
            _assert_safe_identifier(slug_column)
            result = session.execute(
                text(
                    f"""
                    UPDATE {table_name}
                    SET owner_user_id = COALESCE((
                        SELECT MAX(sa_industries.user_id)
                        FROM sa_industries
                        WHERE sa_industries.slug = {table_name}.{slug_column}
                          AND sa_industries.user_id IS NOT NULL
                    ), '')
                    WHERE (owner_user_id IS NULL OR owner_user_id = '')
                      AND {slug_column} NOT IN (
                          SELECT slug FROM sa_industries
                          GROUP BY slug
                          HAVING COUNT(DISTINCT user_id) > 1
                      )
                    """
                )
            )
            count = getattr(result, "rowcount", 0) or 0
            if count:
                updated.append(f"{table_name}:{count}")

        # Backfill sa_collected_videos from TaskQueue.video_id -> aweme_id
        ambiguous_aweme = {
            row[0]
            for row in session.execute(
                text(
                    """
                    SELECT video_id FROM sa_task_queue
                    WHERE video_id IS NOT NULL AND video_id != ''
                    GROUP BY video_id
                    HAVING COUNT(DISTINCT owner_user_id) > 1
                    """
                )
            )
        }
        if ambiguous_aweme:
            log.warning(
                "Skipping backfill for ambiguous aweme_ids mapped to multiple owners: %s",
                sorted(ambiguous_aweme)[:50],
            )

        result = session.execute(
            text(
                """
                UPDATE sa_collected_videos
                SET owner_user_id = COALESCE((
                    SELECT MAX(sa_task_queue.owner_user_id)
                    FROM sa_task_queue
                    WHERE sa_task_queue.video_id = sa_collected_videos.aweme_id
                      AND sa_task_queue.owner_user_id IS NOT NULL
                      AND sa_task_queue.owner_user_id != ''
                ), '')
                WHERE (owner_user_id IS NULL OR owner_user_id = '')
                  AND aweme_id NOT IN (
                      SELECT video_id FROM sa_task_queue
                      WHERE video_id IS NOT NULL AND video_id != ''
                      GROUP BY video_id
                      HAVING COUNT(DISTINCT owner_user_id) > 1
                  )
                """
            )
        )
        count = getattr(result, "rowcount", 0) or 0
        if count:
            updated.append(f"sa_collected_videos:{count}")

        session.commit()
    return updated


def initialize_database(base, engine: Engine) -> list[str]:
    """Create known tables and run safe additive migrations."""

    base.metadata.create_all(bind=engine)
    added = _add_missing_columns(engine)
    backfilled = _backfill_owner_user_id(engine)
    if backfilled:
        added.extend(f"backfill {item}" for item in backfilled)
    if added:
        log.info("Applied additive database migrations: %s", ", ".join(added))
    return added


def verify_matrix_schema(engine: Engine) -> dict:
    """Return readiness details for Phase 1 matrix/agent tables."""

    required_tables = {
        "sa_device_state",
        "sa_task_graphs",
        "sa_agent_memory",
        "sa_screen_snapshots",
        "sa_execution_logs",
    }
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    missing = sorted(required_tables - existing)
    return {
        "ok": not missing,
        "missing_tables": missing,
        "required_tables": sorted(required_tables),
    }
