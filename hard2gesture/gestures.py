"""The gestures the app recognizes, and the cooldown that stops them repeating."""
from dataclasses import dataclass
from enum import Enum


class Gesture(Enum):
    # Values are stable ids: config.json uses them to bind gestures to actions.
    SWIPE_UP = "swipe_up"
    SWIPE_DOWN = "swipe_down"
    SWIPE_LEFT = "swipe_left"
    SWIPE_RIGHT = "swipe_right"
    FIST_HOLD = "fist_hold"
    SCROLL = "scroll"
    HANDS_APART = "hands_apart"
    HANDS_TOGETHER = "hands_together"
    PINCH = "pinch"
    DOUBLE_PINCH = "double_pinch"

    @property
    def label(self) -> str:
        """E.g. "swipe up"."""
        return self.value.replace("_", " ")


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
    # PINCH only: when the user aimed, just before the thumb started closing (time.monotonic()).
    aim_time: float | None = None


class Cooldown:
    """Blocks any gesture for cooldown_s after the last one, and its opposite for
    opposite_cooldown_s, so moving the hand back doesn't count as a gesture the other way."""

    def __init__(self, cooldown_s: float, opposite_cooldown_s: float):
        self._cooldown_s = cooldown_s
        self._opposite_cooldown_s = opposite_cooldown_s
        self._last_gesture: Gesture | None = None
        self._last_gesture_time = float("-inf")

    def allows(self, gesture: Gesture, now: float) -> bool:
        time_since_last = now - self._last_gesture_time
        if time_since_last < self._cooldown_s:
            return False
        is_return_stroke = gesture is OPPOSITE.get(self._last_gesture)
        return not (is_return_stroke and time_since_last < self._opposite_cooldown_s)

    def record(self, gesture: Gesture, now: float):
        self._last_gesture = gesture
        self._last_gesture_time = now
