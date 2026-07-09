from server.api.jobs import _normalize_job_status, _job_operational_flags


def test_collect_job_done_with_no_source_comments():
    """A collect job that completes with zero comments should surface the restriction clearly."""
    status, label, reason = _normalize_job_status(
        job_type="collect",
        raw_status="done",
        send_summary=None,
        collect_summary={
            "candidate_comments": 0,
            "empty_reason": "no_source_comments",
            "warning": "MediaCrawler completed but produced no source comments...",
        },
        error=None,
        latest_execution=None,
        latest_snapshot=None,
    )
    assert status == "needs_attention"
    assert "关注" in label or "完成" in label
    assert "no source comments" in reason.lower() or "平台未返回" in reason


def test_collect_job_done_with_no_data():
    """A collect job that returns zero comments without a known restriction should be no_data."""
    status, label, reason = _normalize_job_status(
        job_type="collect",
        raw_status="done",
        send_summary=None,
        collect_summary={"candidate_comments": 0},
        error=None,
        latest_execution=None,
        latest_snapshot=None,
    )
    assert status == "no_data"
    assert label == "完成但未采集到数据"


def test_collect_job_done_with_enqueued_comments():
    """A collect job that successfully enqueues comments should be done."""
    status, label, reason = _normalize_job_status(
        job_type="collect",
        raw_status="done",
        send_summary=None,
        collect_summary={"candidate_comments": 10, "enqueued": 5},
        error=None,
        latest_execution=None,
        latest_snapshot=None,
    )
    assert status == "done"
    assert label == "已完成"
    assert reason == ""


def test_collect_job_failed_surfaces_error():
    """A failed collect job should expose the error/collect_summary warning."""
    status, label, reason = _normalize_job_status(
        job_type="collect",
        raw_status="failed",
        send_summary=None,
        collect_summary={
            "phase": "discover_timeout",
            "warning": "Discovery timed out before MediaCrawler returned source comments.",
        },
        error="Timeout",
        latest_execution=None,
        latest_snapshot=None,
    )
    assert status == "failed"
    assert reason in (
        "Timeout",
        "Discovery timed out before MediaCrawler returned source comments.",
    )


def test_collect_no_data_is_retryable():
    """no_data and needs_attention collect jobs should be retryable."""
    flags = _job_operational_flags(
        raw_status="done",
        normalized_status="no_data",
        error=None,
        final_reason="完成但未采集到匹配评论",
    )
    assert flags["can_retry"] is True
    assert flags["quota_released"] is True
    assert "完成但未采集到匹配评论" in flags["failure_reason"]


def test_collect_needs_attention_is_retryable():
    flags = _job_operational_flags(
        raw_status="done",
        normalized_status="needs_attention",
        error=None,
        final_reason="平台未返回任何评论数据",
    )
    assert flags["can_retry"] is True
    assert flags["quota_released"] is True
