"""Turning a pointing hand's movement into cursor movement, like a finger on a touchpad."""
from collections import deque
from math import hypot

# Hand speeds (frame widths per second, at the reference hand size) between which acceleration
# ramps from its slowest to its fastest: about 3 cm/s and 50 cm/s at 60 cm from the camera.
SLOW_HAND_SPEED = 0.05
FAST_HAND_SPEED = 0.8
# How long the cursor's recent positions are kept, for clicks that land where the user aimed.
HISTORY_S = 0.5


def acceleration_gain(hand_speed: float, acceleration: float) -> float:
    """How much farther the cursor goes for a hand moving at hand_speed than at a moderate pace.

    A creeping hand gets less than 1, for pixel-precise aiming; a fast one up to 1 + acceleration,
    to cross the screen. 0 acceleration is a plain 1.
    """
    slowest = 1 / (1 + acceleration / 2)
    fastest = 1 + acceleration
    t = min(max((hand_speed - SLOW_HAND_SPEED) / (FAST_HAND_SPEED - SLOW_HAND_SPEED), 0.0), 1.0)
    ramp = t * t * (3 - 2 * t)  # smoothstep: no sudden change in gain
    return slowest + (fastest - slowest) * ramp


class CursorMapper:
    """Where the cursor goes as the pointing hand moves: it moves by how far the hand moves, faster
    the faster the hand moves, from wherever it already is, so it never jumps when pointing starts.

    Positions in: frame widths. Positions out: screen pixels (floats, for smooth sub-pixel motion).
    """

    def __init__(self, speed: float, acceleration: float, screen_width: int,
                 bounds: tuple[int, int, int, int]):
        """`bounds` is (left, top, right, bottom) of the area the cursor stays in, right and bottom excluded."""
        self.speed = speed
        self.acceleration = acceleration
        self.screen_width = screen_width
        self.bounds = bounds
        self._target: tuple[float, float] | None = None
        self._last_hand: tuple[float, float] | None = None
        self._last_time = 0.0
        self._segment: int | None = None
        self._history: deque[tuple[float, tuple[float, float]]] = deque()  # (time, target)

    @property
    def target(self) -> tuple[float, float] | None:
        return self._target

    def start(self, cursor: tuple[float, float]):
        """Carry on from the cursor's current position (pointing started, or the mouse moved it)."""
        self._target = self._clamp(cursor)
        self._last_hand = None
        self._history.clear()

    def stop(self):
        self._target = None
        self._last_hand = None
        self._history.clear()

    def update(self, hand: tuple[float, float], segment: int, scale: float, now: float) -> tuple[float, float]:
        """The cursor's new target for the hand at `hand`. start() must have been called first.

        A new `segment` means the hand position jumped rather than moved, so it isn't followed.
        `scale` is the hand's size relative to the reference size: a far-off hand, which moves
        less across the frame, moves the cursor as much as a near one.
        """
        assert self._target is not None, "start() first"
        if self._last_hand is not None and segment == self._segment and now > self._last_time:
            dx = (hand[0] - self._last_hand[0]) / scale
            dy = (hand[1] - self._last_hand[1]) / scale
            hand_speed = hypot(dx, dy) / (now - self._last_time)
            pixels_per_frame_width = self.speed * self.screen_width * acceleration_gain(hand_speed, self.acceleration)
            self._target = self._clamp((self._target[0] + dx * pixels_per_frame_width,
                                        self._target[1] + dy * pixels_per_frame_width))
        self._last_hand, self._last_time, self._segment = hand, now, segment
        self._remember(now)
        return self._target

    def rewind_to(self, then: float) -> tuple[float, float] | None:
        """Move the target back to where it was at time `then` (or the oldest remembered), and return it."""
        if not self._history:
            return self._target
        target = self._history[0][1]
        for time, past_target in self._history:
            if time > then:
                break
            target = past_target
        self._target = target
        return target

    def jump_to(self, position: tuple[float, float]):
        self._target = self._clamp(position)

    def _remember(self, now: float):
        history = self._history
        history.append((now, self._target))
        while now - history[0][0] > HISTORY_S:
            history.popleft()

    def _clamp(self, position: tuple[float, float]) -> tuple[float, float]:
        left, top, right, bottom = self.bounds
        return min(max(position[0], left), right - 1), min(max(position[1], top), bottom - 1)
