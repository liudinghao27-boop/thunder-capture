from dataclasses import dataclass

from core.task.router import DispatchRequest, DispatchResult, TaskRouter


@dataclass
class HandlerResult:
    status: str
    message: str


def test_dispatch_accepts_dataclass_handler_result():
    router = TaskRouter()
    router.register("douyin", "send_dm", lambda request: HandlerResult("queued", request.device_id))

    result = router.dispatch(DispatchRequest(device_id="device-1"))

    assert result == DispatchResult(True, "queued", "device-1", "douyin:send_dm")


def test_dispatch_preserves_dispatch_result_and_fills_route():
    router = TaskRouter()
    router.register("douyin", "send_dm", lambda request: DispatchResult(True, "done", "ok"))

    result = router.dispatch(DispatchRequest())

    assert result == DispatchResult(True, "done", "ok", "douyin:send_dm")
