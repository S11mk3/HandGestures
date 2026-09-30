"""Pointing with the index finger moves the cursor; pinching the thumb onto it clicks."""
from collections import deque
from math import dist, hypot, pi

from .config import Config
from .gestures import Gesture, GestureEvent
from .hand_landmarks import HandLandmark, Landmarks

# A pinch lets go only once the fingertips are this many times pinch_distance apart,
# so fingertips hovering around pinch_distance don't click again and again.
PINCH_RELEASE_FACTOR = 1.5
# Closing the thumb on the index finger drags the fingertip along, so a click lands where the
# pointer was before the thumb started closing, looking back at most this long.
PINCH_REWIND_S = 0.3
# A second pinch this close to the first (fraction of the frame) clicks exactly where the
# first did: Windows only sees a double click if both land within a few pixels.
DOUBLE_PINCH_RADIUS = 0.03
# How quickly (Hz) the filter follows changes in the fingertip's speed: higher lets it
# catch up sooner when the finger starts moving.
SPEED_CUTOFF_HZ = 2.0


def pinch_ratio(landmarks: Landmarks) -> float:
    """The gap between the thumb and index fingertips, as a fraction of the palm's length."""
    palm_length = dist(landmarks[HandLandmark.WRIST][:2], landmarks[HandLandmark.MIDDLE_FINGER_MCP][:2])
    gap = dist(landmarks[HandLandmark.THUMB_TIP][:2], landmarks[HandLandmark.INDEX_FINGER_TIP][:2])
    return gap / max(palm_length, 1e-6)


class OneEuroFilter:
    """Smooths a moving point: strongly while it's nearly still, hiding tracking jitter, and
    lightly while it moves fast, so it doesn't lag. See https://gery.casiez.net/1euro/"""

    def __init__(self, min_cutoff_hz: float, speed_coefficient: float):
        self._min_cutoff_hz = min_cutoff_hz
        self._speed_coefficient = speed_coefficient
        self.reset()

    def reset(self):
        self._position: tuple[float, float] | None = None
        self._velocity = (0.0, 0.0)
        self._time = 0.0

    def smooth(self, position: tuple[float, float], now: float) -> tuple[float, float]:
        if self._position is None:
            self._position, self._time = position, now
            return position
        elapsed = now - self._time
        if elapsed <= 0:
            return self._position
        raw_velocity = [(new - old) / elapsed for new, old in zip(position, self._position)]
        self._velocity = _low_pass(raw_velocity, self._velocity, SPEED_CUTOFF_HZ, elapsed)
        cutoff_hz = self._min_cutoff_hz + self._speed_coefficient * hypot(*self._velocity)
        self._position = _low_pass(position, self._position, cutoff_hz, elapsed)
        self._time = now
        return self._position


def _low_pass(new, previous, cutoff_hz: float, elapsed_s: float) -> tuple[float, float]:
    """One step of an exponential low-pass filter with this cutoff frequency."""
    time_constant = 1 / (2 * pi * cutoff_hz)
    weight = 1 / (1 + time_constant / elapsed_s)
    x, y = (old + weight * (value - old) for value, old in zip(new, previous))
    return x, y


class PointerGestures:
    """Call update() once per camera frame while the hand is pointing; it returns the clicks made in that frame.

    `position` is where the pointer should be, in fractions of the frame: the smoothed index
    fingertip, held still while pinched.
    """

    def __init__(self, config: Config):
        self.config = config
        self._filter = OneEuroFilter(config.pointer_smoothing, config.pointer_responsiveness)
        self.reset()

    @property
    def position(self) -> tuple[float, float] | None:
        """None until the first update() after a reset()."""
        return self._position

    @property
    def is_pinched(self) -> bool:
        return self._pinched

    def reset(self):
        """Forget the pointer; called when the hand stops pointing or gestures are paused."""
        self._filter.reset()
        self._position: tuple[float, float] | None = None
        self._recent: deque[tuple[float, float, tuple[float, float]]] = deque()  # (time, pinch ratio, position)
        self._pinched = False
        # A hand that comes into view already pinched hasn't clicked: the fingertips must be seen apart first.
        self._seen_apart = False
        self._last_click_time = float("-inf")
        self._last_click_position = (0.0, 0.0)

    def holds_pinch(self, landmarks: Landmarks) -> bool:
        """Is the hand still pinching? A pinch often curls the index finger, but the hand is still pointing."""
        return self._pinched and pinch_ratio(landmarks) < self._release_distance

    @property
    def _release_distance(self) -> float:
        return self.config.pinch_distance * PINCH_RELEASE_FACTOR

    def update(self, landmarks: Landmarks, now: float) -> list[GestureEvent]:
        fingertip = self._filter.smooth(landmarks[HandLandmark.INDEX_FINGER_TIP][:2], now)
        ratio = pinch_ratio(landmarks)
        recent = self._recent
        recent.append((now, ratio, fingertip))
        while now - recent[0][0] > PINCH_REWIND_S:
            recent.popleft()

        if self._pinched:
            if ratio < self._release_distance:
                return []  # the pointer holds still until the pinch lets go
            self._pinched = False
        if ratio >= self._release_distance:
            self._seen_apart = True
        if ratio < self.config.pinch_distance and self._seen_apart:
            self._pinched = True
            return [self._click(now)]
        self._position = fingertip
        return []

    def _click(self, now: float) -> GestureEvent:
        aimed_at = self._position_before_pinching()
        is_second_click = (now - self._last_click_time < self.config.double_pinch_s
                           and dist(aimed_at, self._last_click_position) < DOUBLE_PINCH_RADIUS)
        if is_second_click:
            self._position = self._last_click_position
            self._last_click_time = float("-inf")  # a third pinch is a new click
            return GestureEvent(Gesture.DOUBLE_PINCH)
        self._position = aimed_at
        self._last_click_time, self._last_click_position = now, aimed_at
        return GestureEvent(Gesture.PINCH)

    def _position_before_pinching(self) -> tuple[float, float]:
        """Where the pointer was before the thumb started closing on the index finger: what the user aimed at.

        Goes back through recent frames while the fingertips were farther apart each frame before.
        """
        samples = reversed(self._recent)
        _, gap, position = next(samples)
        for _, earlier_gap, earlier_position in samples:
            if earlier_gap <= gap:
                break
            gap, position = earlier_gap, earlier_position
        return position
