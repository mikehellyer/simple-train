from simple_train.core.settings import SettingsStore


def test_round_trip_and_bad_values(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.update(port="/dev/ttyUSB0", programming_mode="paged")
    assert SettingsStore(path).settings.port == "/dev/ttyUSB0"
    path.write_text('{"programming_mode": "nonsense", "baud": "fast", "main_address": 44}')
    settings = SettingsStore(path).settings
    assert settings.programming_mode == "direct" and settings.baud == 9600 and settings.main_address == 44
