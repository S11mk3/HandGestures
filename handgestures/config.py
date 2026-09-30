"""User-tunable settings, stored in config.json."""
import json
import logging
from dataclasses import asdict, dataclass

from .paths import CONFIG_PATH

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    # Camera
    camera_index: int = 0
    frame_width: int = 640
    frame_height: int = 480
    # Width of the preview window in pixels; its height follows the camera's aspect ratio.
    preview_width: int = 320

    # Hand detection, 0-1: higher rejects more uncertain hands.
    min_detection_confidence: float = 0.6
    min_tracking_confidence: float = 0.5

    # Swipe: the palm must travel swipe_distance (fraction of the frame) within
    # swipe_window_s, at least swipe_axis_ratio times farther along one axis than the other.
    swipe_distance: float = 0.25
    swipe_window_s: float = 0.4
    swipe_axis_ratio: float = 2.0
    # A newly seen pose must hold this long before it counts, so one misread frame changes nothing.
    pose_confirm_s: float = 0.1
    # A hand hidden for less than this (e.g. by motion blur mid-swipe) doesn't cancel the gesture.
    hand_lost_grace_s: float = 0.2
    # Dead time after a swipe, and a longer block on the reverse direction so that
    # bringing the hand back doesn't swipe the other way.
    cooldown_s: float = 0.8
    opposite_cooldown_s: float = 1.6

    # Two open palms: the gap between them must grow or shrink by two_hand_distance
    # (fraction of the frame width) within two_hand_window_s.
    two_hand_distance: float = 0.3
    two_hand_window_s: float = 0.5
    # After two hands were up, one-hand gestures are ignored this long, so lowering
    # a hand doesn't count as a swipe.
    two_hand_holdoff_s: float = 1.0

    # How long to hold a fist before it toggles play/pause.
    fist_hold_s: float = 1.0

    # Scroll: one step per scroll_step of fingertip travel (fraction of the frame height),
    # and scroll_amount wheel units per step (120 = one notch).
    scroll_step: float = 0.03
    scroll_amount: int = 120

    # Pointer: pointing with the index finger moves the cursor like a finger on a touchpad,
    # pointer_speed screen widths for each frame width the fingertip travels.
    pointer_speed: float = 1.0
    # Pointer smoothing: pointer_smoothing is how quickly (Hz) a still fingertip is followed,
    # lower = steadier but laggier; pointer_responsiveness speeds that up as the finger moves faster.
    pointer_smoothing: float = 2.0
    pointer_responsiveness: float = 30.0
    # While pointing, thumb and index fingertips closer than pinch_distance (fraction of the
    # palm's length) click. Two pinches within double_pinch_s double click: keep it within
    # Windows' double-click speed (0.5 s by default).
    pinch_distance: float = 0.3
    double_pinch_s: float = 0.5


def load_config() -> Config:
    """Return the settings from config.json, with defaults for any it lacks.

    The file is rewritten when settings are missing from it (first run, or an
    update added new ones), keeping the user's values, so every setting is visible.
    """
    defaults = asdict(Config())
    saved = {}
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            log.warning("Ignoring unreadable %s: %s", CONFIG_PATH, error)
            return Config()

    unknown_names = saved.keys() - defaults.keys()
    if unknown_names:
        log.warning("Ignoring unknown settings in %s: %s", CONFIG_PATH, ", ".join(sorted(unknown_names)))
    config = Config(**{name: value for name, value in saved.items() if name in defaults})

    if defaults.keys() - saved.keys():
        CONFIG_PATH.write_text(json.dumps({**defaults, **saved}, indent=2), encoding="utf-8")
    return config
