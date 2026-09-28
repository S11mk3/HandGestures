import json
from dataclasses import asdict

import pytest

from handgestures import config as config_module
from handgestures.config import Config, load_config


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    return path


def test_first_run_writes_all_defaults(config_path):
    assert load_config() == Config()
    assert json.loads(config_path.read_text()) == asdict(Config())


def test_keeps_user_values_and_adds_missing_settings(config_path):
    config_path.write_text(json.dumps({"swipe_distance": 0.25}))
    assert load_config().swipe_distance == 0.25
    saved = json.loads(config_path.read_text())
    assert saved["swipe_distance"] == 0.25
    assert saved["cooldown_s"] == Config().cooldown_s


def test_ignores_unknown_settings_but_keeps_them_in_the_file(config_path):
    config_path.write_text(json.dumps({"old_setting": 1}))
    assert load_config() == Config()
    assert json.loads(config_path.read_text())["old_setting"] == 1


def test_unreadable_file_uses_defaults_and_is_left_alone(config_path):
    config_path.write_text("{not json")
    assert load_config() == Config()
    assert config_path.read_text() == "{not json"
