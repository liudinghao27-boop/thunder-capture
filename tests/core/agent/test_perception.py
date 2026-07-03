from core.agent import perception as perception_module
from core.agent.perception import PerceptionService
from core.device.adb_client import ADBResult


class _FakeADBClient:
    calls: list[tuple[str, ...]] = []

    def __init__(self, serial):
        self.serial = serial

    def shell(self, *args, timeout=5, check=False):
        self.calls.append(tuple(args))
        if args == ("dumpsys", "window", "windows"):
            return ADBResult(["adb"], 0, stdout="Window list without focus")
        return ADBResult(
            ["adb"],
            0,
            stdout=(
                "mCurrentFocus=Window{546b98b mode=0 rootTaskId=1 "
                "u0 com.miui.home/com.miui.home.launcher.Launcher}"
            ),
        )


def test_current_focus_falls_back_to_dumpsys_window(monkeypatch):
    _FakeADBClient.calls = []
    monkeypatch.setattr(perception_module, "ADBClient", _FakeADBClient)

    package_name, activity = PerceptionService()._current_focus("device-1")

    assert package_name == "com.miui.home"
    assert activity == "com.miui.home.launcher.Launcher"
    assert _FakeADBClient.calls == [
        ("dumpsys", "window", "windows"),
        ("dumpsys", "window"),
    ]
