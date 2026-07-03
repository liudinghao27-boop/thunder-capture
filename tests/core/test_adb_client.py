import subprocess

from core.device.adb_client import ADBClient
from core.device.adb_client import ADBResult
from core.device.adb_client import _normalize_visible_text


def test_adb_client_decodes_text_output_as_utf8(monkeypatch):
    def fake_run(command, **kwargs):
        assert kwargs["text"] is False
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="抖音".encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = ADBClient("device-1").shell("echo", "抖音")

    assert result.stdout == "抖音"
    assert result.text == "抖音"


def test_adb_client_input_text_fails_when_unicode_not_visible(monkeypatch):
    client = ADBClient("device-1")
    calls = []

    def fake_shell(*args, timeout=5.0, check=False):
        calls.append(args)
        return ADBResult(["adb", *args], 0, stdout="Broadcast completed: result=0")

    monkeypatch.setattr(client, "shell", fake_shell)
    monkeypatch.setattr(client, "_input_text_verified", lambda expected: False)

    result = client.input_text("验收测试")

    assert result.returncode == 2
    assert "expected Unicode text" in result.stderr
    assert any("ADB_INPUT_B64" in call for call in calls)
    assert any("ADB_INPUT_CHARS" in call for call in calls)


def test_adb_client_input_text_accepts_unicode_after_visible_verification(monkeypatch):
    client = ADBClient("device-1")

    def fake_shell(*args, timeout=5.0, check=False):
        return ADBResult(["adb", *args], 0, stdout="Broadcast completed: result=0")

    monkeypatch.setattr(client, "shell", fake_shell)
    monkeypatch.setattr(client, "_input_text_verified", lambda expected: True)

    result = client.input_text("验收测试")

    assert result.ok is True


def test_normalize_visible_text_unifies_common_ocr_punctuation():
    expected = _normalize_visible_text("验收测试，请\n忽略")
    observed = _normalize_visible_text("验收测试,请忽略")

    assert expected == observed
