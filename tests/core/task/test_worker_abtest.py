from unittest.mock import patch, MagicMock
from core.config import IndustryConfig
from core.task.scheduler import ClaimedTask
from core.task.worker import DeviceWorker


def _make_industry(**overrides):
    defaults = dict(
        name="测试", slug="t", keywords=["a"], categories=["c"],
        reply_tone="默认人设", reply_style="默认风格",
    )
    defaults.update(overrides)
    return IndustryConfig(**defaults)


def _mock_reply_client(content="已生成回复"):
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=content))]
    mock_client.chat.completions.create.return_value = mock_resp
    return mock_client


def test_worker_uses_selected_variant():
    cfg = _make_industry(reply_variants=[
        {"id": "v1", "name": "变体1", "reply_tone": "退伍老兵", "reply_style": "稳重", "weight": 1, "enabled": True},
    ])
    worker = DeviceWorker(device_id="d1", adb_serial="", industry=cfg)

    with patch("core.task.worker._get_reply_client", return_value=_mock_reply_client()):
        reply, variant_id = worker._generate_reply({"text": "我想当兵"})

    assert reply == "已生成回复"
    assert variant_id == "v1"


def test_worker_prompt_contains_variant_tone_and_style():
    cfg = _make_industry(reply_variants=[
        {"id": "v1", "name": "变体1", "reply_tone": "退伍老兵", "reply_style": "稳重", "weight": 1, "enabled": True},
    ])
    worker = DeviceWorker(device_id="d1", adb_serial="", industry=cfg)

    mock_client = _mock_reply_client()
    with patch("core.task.worker._get_reply_client", return_value=mock_client):
        worker._generate_reply({"text": "我想当兵"})

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    prompt = call_kwargs["messages"][0]["content"]
    assert "退伍老兵" in prompt
    assert "稳重" in prompt


def test_worker_uses_default_tone_when_no_variant():
    cfg = _make_industry()
    worker = DeviceWorker(device_id="d1", adb_serial="", industry=cfg)

    mock_client = _mock_reply_client()
    with patch("core.task.worker._get_reply_client", return_value=mock_client):
        worker._generate_reply({"text": "我想当兵"})

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    prompt = call_kwargs["messages"][0]["content"]
    assert "默认人设" in prompt
    assert "默认风格" in prompt


def test_worker_skips_disabled_variants():
    cfg = _make_industry(reply_variants=[
        {"id": "v1", "name": "变体1", "reply_tone": "退伍老兵", "reply_style": "稳重", "weight": 1, "enabled": False},
    ])
    worker = DeviceWorker(device_id="d1", adb_serial="", industry=cfg)

    mock_client = _mock_reply_client()
    with patch("core.task.worker._get_reply_client", return_value=mock_client):
        reply, variant_id = worker._generate_reply({"text": "我想当兵"})

    assert variant_id == ""
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    prompt = call_kwargs["messages"][0]["content"]
    assert "默认人设" in prompt
    assert "默认风格" in prompt
    assert "退伍老兵" not in prompt


def test_variant_id_passed_to_scheduler_on_success():
    cfg = _make_industry(reply_variants=[
        {"id": "v1", "name": "变体1", "reply_tone": "退伍老兵", "reply_style": "稳重", "weight": 1, "enabled": True},
    ])
    worker = DeviceWorker(device_id="d1", adb_serial="", industry=cfg)
    worker._init_agent_safe = MagicMock(return_value=True)

    claim = ClaimedTask(
        task={
            "id": 1,
            "text": "我想当兵",
            "short_id": "123",
            "source_name": "用户",
            "claim_token": "token-1",
        },
        reserved=True,
    )
    no_claim = ClaimedTask(None, reserved=False, reason="no_task")
    worker._scheduler.claim_for_device = MagicMock(side_effect=[claim, no_claim])
    worker._scheduler.commit_task = MagicMock(return_value=True)
    worker._scheduler.release = MagicMock()

    with patch("core.task.worker._get_reply_client", return_value=_mock_reply_client()), \
         patch("core.task.worker.DeviceSupervisor.preflight", return_value=MagicMock(ok=True)), \
         patch("core.task.worker.DeviceSupervisor.mark_finished"), \
         patch("core.task.runner.TaskGraphRunner") as mock_runner_class, \
         patch("core.task.worker.time.sleep"):
        mock_runner = MagicMock()
        mock_runner.run_douyin_dm.return_value = MagicMock(ok=True, message="")
        mock_runner_class.return_value = mock_runner

        summary = worker.run()

    assert summary["sent"] == 1
    worker._scheduler.commit_task.assert_called_with(
        1, "d1", "done", "",
        claim_token="token-1", reply_variant_id="v1"
    )


def test_worker_reads_short_id_from_multiple_keys():
    cfg = _make_industry()
    worker = DeviceWorker(device_id="d1", adb_serial="", industry=cfg)
    worker._init_agent_safe = MagicMock(return_value=True)

    captured = {}

    def _capture_run_douyin_dm(*, search_target, **kwargs):
        captured["search_target"] = search_target
        return MagicMock(ok=True, message="")

    claim = ClaimedTask(
        task={
            "id": 1,
            "text": "hello",
            "douyin_id": "douyin-123",
            "source_name": "用户",
            "claim_token": "token-1",
        },
        reserved=True,
    )
    no_claim = ClaimedTask(None, reserved=False, reason="no_task")
    worker._scheduler.claim_for_device = MagicMock(side_effect=[claim, no_claim])
    worker._scheduler.commit_task = MagicMock(return_value=True)

    with patch("core.task.worker._get_reply_client", return_value=_mock_reply_client()), \
         patch("core.task.worker.DeviceSupervisor.preflight", return_value=MagicMock(ok=True)), \
         patch("core.task.worker.DeviceSupervisor.mark_finished"), \
         patch("core.task.runner.TaskGraphRunner") as mock_runner_class, \
         patch("core.task.worker.time.sleep"):
        mock_runner = MagicMock()
        mock_runner.run_douyin_dm.side_effect = _capture_run_douyin_dm
        mock_runner_class.return_value = mock_runner

        worker.run()

    assert captured["search_target"] == "douyin-123"


def test_worker_passes_send_limits_to_scheduler():
    cfg = _make_industry(daily_send_max=42, global_daily_limit=100)
    setattr(cfg, "hourly_send_limit", 3)
    worker = DeviceWorker(device_id="d1", adb_serial="", industry=cfg, daily_limit=7)
    assert worker._scheduler.daily_send_max == 42
    assert worker._scheduler.global_daily_limit == 100
    assert worker._scheduler.device_daily_limit == 7
    assert worker._scheduler.hourly_send_limit == 3


def test_worker_marks_keyboard_error_when_agent_init_fails():
    cfg = _make_industry()
    worker = DeviceWorker(device_id="d1", adb_serial="serial-1", industry=cfg)
    worker._generate_reply = MagicMock(return_value=("hello", ""))
    worker._init_agent_safe = MagicMock(return_value=False)

    claim = ClaimedTask(
        task={
            "id": 1,
            "text": "hello",
            "short_id": "123",
            "source_name": "user",
            "claim_token": "token-1",
        },
        reserved=True,
    )
    worker._scheduler.claim_for_device = MagicMock(return_value=claim)
    worker._scheduler.commit_task = MagicMock(return_value=True)
    worker._supervisor.preflight = MagicMock(return_value=MagicMock(ok=True))
    worker._supervisor.mark_failure = MagicMock()
    worker._supervisor.mark_finished = MagicMock()

    summary = worker.run()

    assert summary["status"] == "keyboard_error"
    assert summary["failed"] == 1
    worker._supervisor.mark_failure.assert_called_once()
    assert worker._supervisor.mark_failure.call_args.kwargs["status"] == "keyboard_error"
    worker._supervisor.mark_finished.assert_called_once()
    assert worker._supervisor.mark_finished.call_args.kwargs["status"] == "keyboard_error"


def test_worker_isolates_device_on_risk_blocker_result():
    cfg = _make_industry()
    worker = DeviceWorker(device_id="d1", adb_serial="serial-1", industry=cfg)
    worker._generate_reply = MagicMock(return_value=("hello", ""))
    worker._init_agent_safe = MagicMock(return_value=True)

    claim = ClaimedTask(
        task={
            "id": 1,
            "text": "hello",
            "short_id": "123",
            "source_name": "user",
            "claim_token": "token-1",
        },
        reserved=True,
    )
    no_claim = ClaimedTask(None, reserved=False, reason="no_task")
    worker._scheduler.claim_for_device = MagicMock(side_effect=[claim, no_claim])
    worker._scheduler.commit_task = MagicMock(return_value=True)
    worker._supervisor.preflight = MagicMock(return_value=MagicMock(ok=True))
    worker._supervisor.mark_failure = MagicMock()
    worker._supervisor.mark_finished = MagicMock()

    with patch("core.agent.perception.PerceptionService", return_value=MagicMock()), \
         patch("core.task.runner.TaskGraphRunner") as mock_runner_class, \
         patch("core.task.worker.time.sleep"):
        mock_runner = MagicMock()
        mock_runner.run_douyin_dm.return_value = MagicMock(
            ok=False,
            status="blocked",
            message="Blocked before execution: risk_control",
        )
        mock_runner_class.return_value = mock_runner

        summary = worker.run()

    assert summary["status"] == "isolated"
    assert summary["failed"] == 1
    worker._scheduler.commit_task.assert_called_once_with(
        1,
        "d1",
        "fail",
        "Blocked before execution: risk_control",
        claim_token="token-1",
    )
    worker._supervisor.mark_failure.assert_called_once()
    assert worker._supervisor.mark_failure.call_args.kwargs["status"] == "isolated"
    assert "risk_control" in worker._supervisor.mark_failure.call_args.kwargs["error"]
    worker._scheduler.claim_for_device.assert_called_once_with("d1")
    worker._supervisor.mark_finished.assert_called_once()
    assert worker._supervisor.mark_finished.call_args.kwargs["status"] == "isolated"


def test_generate_reply_handles_none_content():
    cfg = _make_industry(reply_tone="助手")
    worker = DeviceWorker(device_id="d1", adb_serial="", industry=cfg)

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=None))]
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("core.task.worker._get_reply_client", return_value=mock_client):
        reply, variant_id = worker._generate_reply({"text": "hello"})

    assert reply != ""
    assert isinstance(reply, str)
