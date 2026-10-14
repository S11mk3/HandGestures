"""User settings: their defaults and allowed ranges, config.json, and the store that applies changes live."""
import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .bindings import ACTIONS, DEFAULT_GESTURE_ACTIONS
from .paths import CONFIG_PATH

log = logging.getLogger(__name__)

CONFIG_VERSION = 1
# Settings whose meaning changed in version 1: distances now follow the hand's size in the frame,
# and the pointer gained acceleration. Values saved by earlier versions are replaced by the new defaults.
CHANGED_IN_VERSION_1 = {"swipe_distance", "scroll_step", "pointer_speed", "pointer_smoothing", "pointer_responsiveness"}


def _setting(default, low=None, high=None):
    """A Config field, with the range its value is clamped to when settings are loaded or changed."""
    return field(default=default, metadata={"range": (low, high)})


@dataclass(frozen=True)
class Config:
    # General
    calibrate_on_start: bool = True
    show_preview_on_start: bool = True
    # With no hand in view for a few seconds, look for one only a few times a second.
    battery_saver: bool = True
    show_debug_info: bool = False  # tracking details on the camera preview
    first_run_done: bool = False  # the gesture guide has been shown once

    # Camera
    camera_index: int = _setting(0, 0, 9)
    frame_width: int = _setting(640, 160, 1920)
    frame_height: int = _setting(480, 120, 1080)

    # Hand detection, 0-1: higher rejects more uncertain hands.
    min_detection_confidence: float = _setting(0.6, 0.3, 0.9)
    min_tracking_confidence: float = _setting(0.5, 0.3, 0.9)

    # Gesture id -> action id (see bindings.py), for the gestures whose action the user picks.
    gesture_actions: dict = field(default_factory=lambda: dict(DEFAULT_GESTURE_ACTIONS))
    pointer_enabled: bool = True
    scroll_enabled: bool = True

    # Distances below are fractions of the frame's width (along both axes), for a hand about
    # 60 cm from the camera; they scale with the hand's size in the frame, so they stay the same
    # relative to the hand whether the user sits near the camera or far from it.

    # Swipe: the palm must travel swipe_distance within swipe_window_s, at least swipe_axis_ratio
    # times farther along one axis than the other.
    swipe_distance: float = _setting(0.22, 0.08, 0.5)
    swipe_window_s: float = _setting(0.4, 0.15, 1.0)
    swipe_axis_ratio: float = _setting(2.0, 1.0, 5.0)
    # A newly seen pose must hold this long before it counts, so one misread frame changes nothing.
    pose_confirm_s: float = _setting(0.1, 0.0, 0.5)
    # A hand hidden for less than this (e.g. by motion blur mid-swipe) doesn't cancel the gesture.
    hand_lost_grace_s: float = _setting(0.2, 0.0, 1.0)
    # Dead time after a swipe, and a longer block on the reverse direction so that
    # bringing the hand back doesn't swipe the other way.
    cooldown_s: float = _setting(0.8, 0.0, 3.0)
    opposite_cooldown_s: float = _setting(1.6, 0.0, 5.0)

    # Two open palms: the gap between them must grow or shrink by two_hand_distance within two_hand_window_s.
    two_hand_distance: float = _setting(0.3, 0.1, 0.8)
    two_hand_window_s: float = _setting(0.5, 0.15, 1.5)
    # After two hands were up, one-hand gestures are ignored this long, so lowering
    # a hand doesn't count as a swipe.
    two_hand_holdoff_s: float = _setting(1.0, 0.0, 3.0)

    # How long to hold a fist before its action runs.
    fist_hold_s: float = _setting(1.0, 0.3, 3.0)

    # Scroll: one step per scroll_step of fingertip travel, and scroll_amount wheel units per step (120 = one notch).
    scroll_step: float = _setting(0.022, 0.005, 0.1)
    scroll_amount: int = _setting(120, 10, 600)

    # Pointer: pointing with the index finger moves the cursor like a finger on a touchpad,
    # pointer_speed screen widths for each frame width the hand travels at a moderate pace.
    pointer_speed: float = _setting(1.0, 0.2, 4.0)
    # How much faster the cursor goes when the hand moves fast (and slower when it creeps): 0 = never.
    pointer_acceleration: float = _setting(1.0, 0.0, 3.0)
    # Higher = steadier pointer but more lag. Multiplies the smoothing calibration picked for the camera.
    pointer_smoothing: float = _setting(1.0, 0.25, 4.0)
    # How much the smoothing lets up while the hand moves fast, so fast moves don't lag.
    pointer_responsiveness: float = _setting(30.0, 0.0, 100.0)
    # While pointing, thumb and index fingertips closer than pinch_distance (fraction of the
    # palm's length) click. Two pinches within double_pinch_s double click: keep it within
    # Windows' double-click speed (0.5 s by default).
    pinch_distance: float = _setting(0.3, 0.1, 0.6)
    double_pinch_s: float = _setting(0.5, 0.2, 1.0)


def validated(values: dict) -> dict:
    """The settings in `values`, checked: wrong types fall back to the default, numbers out of range are clamped."""
    defaults = Config()
    checked = {}
    for setting in fields(Config):
        name = setting.name
        default = getattr(defaults, name)
        value = values.get(name, default)
        if name == "gesture_actions":
            checked[name] = _validated_gesture_actions(value)
            continue
        if not _is_type_of(value, default):
            log.warning("Setting %s=%r should be a %s; using %r", name, value, type(default).__name__, default)
            checked[name] = default
            continue
        if isinstance(default, float):
            value = float(value)
        low, high = setting.metadata.get("range", (None, None))
        clamped = value
        if low is not None:
            clamped = max(clamped, low)
        if high is not None:
            clamped = min(clamped, high)
        if clamped != value:
            log.warning("Setting %s=%r is out of range; using %r", name, value, clamped)
        checked[name] = clamped
    return checked


def _is_type_of(value, default) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(default, float):
        return isinstance(value, int | float) and not isinstance(value, bool)
    return isinstance(value, type(default))


def _validated_gesture_actions(value) -> dict[str, str]:
    """Every bindable gesture with a known action: unknown entries are dropped, missing ones get the default."""
    if not isinstance(value, dict):
        log.warning("Setting gesture_actions should map gestures to actions; using the defaults")
        return dict(DEFAULT_GESTURE_ACTIONS)
    checked = {}
    for gesture_id, default_action in DEFAULT_GESTURE_ACTIONS.items():
        action = value.get(gesture_id, default_action)
        if action not in ACTIONS:
            log.warning("Unknown action %r for %s; using %r", action, gesture_id, default_action)
            action = default_action
        checked[gesture_id] = action
    unknown = value.keys() - DEFAULT_GESTURE_ACTIONS.keys()
    if unknown:
        log.warning("Ignoring unknown gestures in gesture_actions: %s", ", ".join(sorted(map(str, unknown))))
    return checked


def load_config(path: Path | None = None) -> Config:
    """Return the settings from config.json, with defaults for any it lacks.

    The file is rewritten when settings are missing from it (first run, or an update added
    new ones) or invalid, keeping the user's other values, so every setting is visible.
    """
    config, _ = _load(path or CONFIG_PATH)
    return config


def _load(path: Path) -> tuple[Config, dict]:
    """The settings, and any unknown entries in the file, which are kept when it's rewritten."""
    saved = {}
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError("not a JSON object")
        except (OSError, ValueError) as error:
            log.warning("Ignoring unreadable %s: %s", path, error)
            return Config(), {}

    saved_version = saved.pop("version", 0)
    if saved_version < 1:
        reset = CHANGED_IN_VERSION_1 & saved.keys()
        if reset:
            log.info("Settings changed meaning in this version; using the new defaults for %s",
                     ", ".join(sorted(reset)))
        saved = {name: value for name, value in saved.items() if name not in CHANGED_IN_VERSION_1}

    known_names = {setting.name for setting in fields(Config)}
    extra = {name: value for name, value in saved.items() if name not in known_names}
    if extra:
        log.warning("Ignoring unknown settings in %s: %s", path, ", ".join(sorted(extra)))
    config = Config(**validated(saved))

    if saved_version != CONFIG_VERSION or {**asdict(config), **extra} != saved:
        _save(path, config, extra)
    return config, extra


def _save(path: Path, config: Config, extra: dict):
    """Write config.json atomically, so a crash mid-write can't leave a half-written file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial_path = path.with_suffix(".tmp")
        content = {"version": CONFIG_VERSION, **asdict(config), **extra}
        partial_path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        os.replace(partial_path, path)
    except OSError as error:
        log.warning("Could not save %s: %s", path, error)


class ConfigStore:
    """The current settings, changed by the UI (main thread) and read by the camera thread.

    Changes are validated and saved right away. `revision` grows with every change, so the
    camera thread can notice one by comparing it each frame; UI code can subscribe instead.
    """

    def __init__(self, path: Path | None = None):
        self._path = path or CONFIG_PATH
        self._config, self._extra = _load(self._path)
        self.revision = 0
        self._lock = threading.Lock()
        self._listeners: list[Callable[[Config], None]] = []

    @property
    def config(self) -> Config:
        return self._config

    @property
    def path(self) -> Path:
        return self._path

    def update(self, **changes):
        """Change some settings, e.g. update(pointer_speed=1.5); unknown names raise TypeError."""
        unknown = changes.keys() - {setting.name for setting in fields(Config)}
        if unknown:
            raise TypeError(f"Unknown settings: {', '.join(sorted(unknown))}")
        with self._lock:
            config = Config(**validated({**asdict(self._config), **changes}))
            if config == self._config:
                return
            self._config = config
            self.revision += 1
            _save(self._path, config, self._extra)
        for listener in list(self._listeners):
            listener(config)

    def reset_to_defaults(self):
        """Every setting back to its default, except the record that the guide was shown."""
        defaults = asdict(Config())
        defaults["first_run_done"] = self._config.first_run_done
        self.update(**defaults)

    def subscribe(self, listener: Callable[[Config], None]):
        """Call listener(new_config) after every change, on the thread that made it."""
        self._listeners.append(listener)
