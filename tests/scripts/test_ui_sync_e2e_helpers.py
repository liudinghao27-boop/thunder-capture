import json

from scripts.smoke.ui_sync_e2e import (
    SyncMapping,
    compare_ui_snapshot,
    get_payload_path,
    summarize_run,
)


def test_get_payload_path_reads_nested_dicts_and_list_lengths():
    payload = {
        "project": {"industry_count": 2},
        "items": [{"name": "first"}, {"name": "second"}],
    }

    assert get_payload_path(payload, "project.industry_count") == 2
    assert get_payload_path(payload, "items.1.name") == "second"
    assert get_payload_path(payload, "items.length") == 2


def test_compare_ui_snapshot_reports_field_mismatches():
    api_payload = {
        "project": {"industry_count": 3},
        "device_matrix": {"total": 2},
    }
    ui_snapshot = {
        "#stat-industries": "3",
        "#stat-devices": "1",
    }
    mappings = [
        SyncMapping(
            name="project count",
            selector="#stat-industries",
            api_path="project.industry_count",
            kind="int",
        ),
        SyncMapping(
            name="device count",
            selector="#stat-devices",
            api_path="device_matrix.total",
            kind="int",
        ),
    ]

    mismatches = compare_ui_snapshot(api_payload, ui_snapshot, mappings)

    assert len(mismatches) == 1
    assert mismatches[0]["name"] == "device count"
    assert mismatches[0]["expected"] == 2
    assert mismatches[0]["actual"] == 1


def test_summarize_run_is_machine_readable_and_counts_failures():
    summary = summarize_run(
        results=[
            {"name": "dashboard", "ok": True, "mismatches": []},
            {"name": "tasks", "ok": False, "mismatches": [{"name": "row count"}]},
        ],
        started_at="2026-07-03T00:00:00Z",
        duration_seconds=1.25,
    )

    assert summary["ok"] is False
    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    json.dumps(summary)
