"""The gestures the app recognizes, and the cooldown that stops them repeating."""
from dataclasses import dataclass
from enum import Enum

from .config import Config


class Gesture(Enum):
    SWIPE_UP = "swipe up"
    SWIPE_DOWN = "swipe down"
    SWIPE_LEFT = "swipe left"
    SWIPE_RIGHT = "swipe right"
    FIST_HOLD = "fist hold"
    SCROLL = "scroll"
    HANDS_APART = "hands apart"
    HANDS_TOGETHER = "hands together"


OPPOSITE = {
    Gesture.SWIPE_UP: Gesture.SWIPE_DOWN,
    Gesture.SWIPE_DOWN: Gesture.SWIPE_UP,
    Gesture.SWIPE_LEFT: Gesture.SWIPE_RIGHT,
    Gesture.SWIPE_RIGHT: Gesture.SWIPE_LEFT,
    Gesture.HANDS_APART: Gesture.HANDS_TOGETHER,
    Gesture.HANDS_TOGETHER: Gesture.HANDS_APART,
}


@dataclass(frozen=True)
class GestureEvent:
    gesture: Gesture
    scroll_steps: int = 0  # SCROLL only; positive = up

    def __str__(self):
        if self.gesture is Gesture.SCROLL:
            return f"{self.gesture.value} {self.scroll_steps:+d}"
        return self.gesture.value


class Cooldown:
    """Blocks any gesture for cooldown_s after the last one, and its opposite for
    opposite_cooldown_s, so moving the hand back doesn't count as a gesture the other way."""

    def __init__(self, config: Config):
        self._config = config
        self._last_gesture: Gesture | None = None
        self._last_gesture_time = float("-inf")

    def allows(self, gesture: Gesture, now: float) -> bool:
        time_since_last = now - self._last_gesture_time
        if time_since_last < self._config.cooldown_s:
            return False
        is_return_stroke = gesture is OPPOSITE.get(self._last_gesture)
        return not (is_return_stroke and time_since_last < self._config.opposite_cooldown_s)

    def record(self, gesture: Gesture, now: float):
        self._last_gesture = gesture
        self._last_gesture_time = now
