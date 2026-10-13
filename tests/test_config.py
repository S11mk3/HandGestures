import json
from dataclasses import asdict

import pytest

from handgestures.bindings import DEFAULT_GESTURE_ACTIONS
from handgestures.config import CONFIG_VERSION, Config, ConfigStore, load_config


@pytest.fixture
def config_path(tmp_path):
    return tmp_path / "config.json"


def saved(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_first_run_writes_all_defaults(config_path):
    assert load_config(config_path) == Config()
    assert saved(config_path) == {"version": CONFIG_VERSION, **asdict(Config())}


def test_keeps_user_values_and_adds_missing_settings(config_path):
    config_path.write_text(json.dumps({"version": 1, "swipe_distance": 0.3}))
    assert load_config(config_path).swipe_distance == 0.3
    assert saved(config_path)["swipe_distance"] == 0.3
    assert saved(config_path)["cooldown_s"] == Config().cooldown_s


def test_settings_from_before_version_1_that_changed_meaning_are_reset(config_path):
    config_path.write_text(json.dumps({"swipe_distance": 0.3, "pointer_speed": 2.5, "cooldown_s": 1.2}))
    config = load_config(config_path)
    assert config.swipe_distance == Config().swipe_distance
    assert config.pointer_speed == Config().pointer_speed
    assert config.cooldown_s == 1.2  # unchanged meaning: kept


def test_ignores_unknown_settings_but_keeps_them_in_the_file(config_path):
    config_path.write_text(json.dumps({"version": 1, "old_setting": 1}))
    assert load_config(config_path) == Config()
    assert saved(config_path)["old_setting"] == 1


def test_unreadable_file_uses_defaults_and_is_left_alone(config_path):
    config_path.write_text("{not json")
    assert load_config(config_path) == Config()
    assert config_path.read_text() == "{not json"


def test_wrong_types_fall_back_and_out_of_range_values_are_clamped(config_path):
    config_path.write_text(json.dumps({"version": 1, "pointer_speed": "fast", "camera_index": True,
                                       "cooldown_s": 99, "scroll_amount": 5, "fist_hold_s": 2}))
    config = load_config(config_path)
    assert config.pointer_speed == Config().pointer_speed
    assert config.camera_index == 0
    assert config.cooldown_s == 3.0
    assert config.scroll_amount == 10
    assert config.fist_hold_s == 2.0 and isinstance(config.fist_hold_s, float)


def test_gesture_actions_are_checked(config_path):
    config_path.write_text(json.dumps({"version": 1, "gesture_actions": {
        "fist_hold": "mute", "swipe_up": "launch_rockets", "wave": "minimize"}}))
    actions = load_config(config_path).gesture_actions
    assert actions["fist_hold"] == "mute"
    assert actions["swipe_up"] == DEFAULT_GESTURE_ACTIONS["swipe_up"]
    assert "wave" not in actions
    assert actions.keys() == DEFAULT_GESTURE_ACTIONS.keys()


def test_store_saves_changes_and_tells_listeners(config_path):
    store = ConfigStore(config_path)
    heard = []
    store.subscribe(heard.append)
    store.update(pointer_speed=2.0)
    assert store.config.pointer_speed == 2.0
    assert store.revision == 1
    assert saved(config_path)["pointer_speed"] == 2.0
    assert heard == [store.config]
    store.update(pointer_speed=2.0)  # no change: no new revision
    assert store.revision == 1


def test_store_rejects_unknown_settings(config_path):
    with pytest.raises(TypeError):
        ConfigStore(config_path).update(warp_speed=9)


def test_reset_keeps_the_record_of_the_first_run(config_path):
    store = ConfigStore(config_path)
    store.update(first_run_done=True, pointer_speed=2.0)
    store.reset_to_defaults()
    assert store.config.pointer_speed == Config().pointer_speed
    assert store.config.first_run_done
