"""Pointing with the index finger moves the cursor; pinching the thumb onto it clicks."""
from collections import deque
from math import dist, hypot, pi

from .gestures import Gesture, GestureEvent
from .hand_landmarks import Hand, HandLandmark

# The point the cursor follows: the index finger's knuckle. Unlike the fingertip, it stays put
# when the thumb closes on the finger or the finger curls, so a click lands where the user aimed.
TRACKED_POINT = HandLandmark.INDEX_FINGER_MCP
# A pinch lets go only once the fingertips are this many times pinch_distance apart,
# so fingertips hovering around pinch_distance don't click again and again.
PINCH_RELEASE_FACTOR = 1.5
# Closing the thumb can still nudge the hand, so a click lands where the cursor was before the
# thumb started closing, looking back at most this long.
PINCH_REWIND_S = 0.3
# A second pinch this close to the first (frame widths, at the reference hand size) double clicks
# where the first clicked: Windows only sees a double click if both land within a few pixels.
DOUBLE_PINCH_RADIUS = 0.03
# How quickly (Hz) the filter follows changes in the hand's speed: higher lets it
# catch up sooner when the hand starts moving.
SPEED_CUTOFF_HZ = 2.0
# Smoothing (Hz) for a still hand when calibration hasn't measured the camera's jitter.
DEFAULT_POINTER_CUTOFF_HZ = 2.0


def pinch_ratio(hand: Hand) -> float:
    """The gap between the thumb and index fingertips, as a fraction of the palm's length.

    Measured on the hand's 3D shape, so turning the hand or moving it nearer doesn't change it.
    """
    world = hand.world
    palm_length = dist(world[HandLandmark.WRIST], world[HandLandmark.MIDDLE_FINGER_MCP])
    gap = dist(world[HandLandmark.THUMB_TIP], world[HandLandmark.INDEX_FINGER_TIP])
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

    def smooth(self, position: tuple[float, float], now: float, speed_scale: float = 1.0) -> tuple[float, float]:
        """The smoothed position. Speeds are divided by speed_scale, so a far-off hand, which moves
        less across the frame, gets the same responsiveness as a near one."""
        if self._position is None:
            self._position, self._time = position, now
            return position
        elapsed = now - self._time
        if elapsed <= 0:
            return self._position
        raw_velocity = [(new - old) / elapsed for new, old in zip(position, self._position)]
        self._velocity = _low_pass(raw_velocity, self._velocity, SPEED_CUTOFF_HZ, elapsed)
        speed = hypot(*self._velocity) / max(speed_scale, 1e-6)
        cutoff_hz = self._min_cutoff_hz + self._speed_coefficient * speed
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

    `position` is where the hand points, in frame widths: the smoothed knuckle, held still while
    pinched. `segment` changes whenever the position jumps (pointing starts, a pinch lets go):
    whoever moves the cursor by the position's changes should start over from there.
    """

    def __init__(self, pinch_distance: float, double_pinch_s: float, min_cutoff_hz: float,
                 speed_coefficient: float):
        self._pinch_distance = pinch_distance
        self._double_pinch_s = double_pinch_s
        self._filter = OneEuroFilter(min_cutoff_hz, speed_coefficient)
        self.segment = 0
        self.reset()

    @property
    def position(self) -> tuple[float, float] | None:
        """None until the first update() after a reset()."""
        return self._position

    @property
    def is_pinched(self) -> bool:
        return self._pinched

    @property
    def last_pinch_ratio(self) -> float | None:
        return self._recent[-1][1] if self._recent else None

    def reset(self):
        """Forget the pointer; called when the hand stops pointing or gestures are paused."""
        self._filter.reset()
        self._position: tuple[float, float] | None = None
        self._recent: deque[tuple[float, float]] = deque()  # (time, pinch ratio)
        self._pinched = False
        # A hand that comes into view already pinched hasn't clicked: the fingertips must be seen apart first.
        self._seen_apart = False
        self._last_click_time = float("-inf")
        self._last_click_position = (0.0, 0.0)
        self.segment += 1

    def holds_pinch(self, hand: Hand) -> bool:
        """Is the hand still pinching? A pinch often curls the index finger, but the hand is still pointing."""
        return self._pinched and pinch_ratio(hand) < self._release_distance

    @property
    def _release_distance(self) -> float:
        return self._pinch_distance * PINCH_RELEASE_FACTOR

    def update(self, hand: Hand, now: float, scale: float = 1.0) -> list[GestureEvent]:
        """`scale` is the hand's size relative to the reference size (see HandScale)."""
        position = self._filter.smooth(hand.point(TRACKED_POINT), now, speed_scale=scale)
        ratio = pinch_ratio(hand)
        recent = self._recent
        recent.append((now, ratio))
        while now - recent[0][0] > PINCH_REWIND_S:
            recent.popleft()

        if self._pinched:
            if ratio < self._release_distance:
                return []  # the pointer holds still until the pinch lets go
            self._pinched = False
            self.segment += 1  # the hand may have drifted while pinched: carry on from where it is now
        if ratio >= self._release_distance:
            self._seen_apart = True
        if ratio < self._pinch_distance and self._seen_apart:
            self._pinched = True
            return [self._click(now, scale)]
        self._position = position
        return []

    def _click(self, now: float, scale: float) -> GestureEvent:
        position = self._position or (0.0, 0.0)
        is_second_click = (now - self._last_click_time < self._double_pinch_s
                           and dist(position, self._last_click_position) < DOUBLE_PINCH_RADIUS * scale)
        if is_second_click:
            self._last_click_time = float("-inf")  # a third pinch is a new click
            return GestureEvent(Gesture.DOUBLE_PINCH)
        self._last_click_time, self._last_click_position = now, position
        return GestureEvent(Gesture.PINCH, aim_time=self._time_before_pinching())

    def _time_before_pinching(self) -> float:
        """When the thumb started closing on the index finger: the cursor was where the user aimed then.

        Goes back through recent frames while the fingertips were farther apart each frame before.
        """
        samples = reversed(self._recent)
        time, gap = next(samples)
        for earlier_time, earlier_gap in samples:
            if earlier_gap <= gap:
                break
            time, gap = earlier_time, earlier_gap
        return time
