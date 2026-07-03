from core.device.manager import MatrixDevice, load_active_devices


def test_web_user_does_not_fallback_to_yaml_when_no_db_devices(monkeypatch):
    monkeypatch.setattr("core.device.manager._load_from_server_db", lambda user_id, device_ids: [])
    monkeypatch.setattr(
        "core.device.manager._load_from_system_yaml",
        lambda device_ids: [MatrixDevice(id="yaml-1", adb_serial="serial-yaml")],
    )

    devices = load_active_devices(user_id="user-1")

    assert devices == []


def test_web_user_falls_back_to_yaml_when_db_is_unavailable(monkeypatch):
    def raise_db_error(user_id, device_ids):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("core.device.manager._load_from_server_db", raise_db_error)
    monkeypatch.setattr(
        "core.device.manager._load_from_system_yaml",
        lambda device_ids: [MatrixDevice(id="yaml-1", adb_serial="serial-yaml")],
    )

    devices = load_active_devices(user_id="user-1")

    assert [device.id for device in devices] == ["yaml-1"]
