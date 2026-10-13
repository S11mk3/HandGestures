"""Gestures made with one hand: swiping an open palm, holding a fist, scrolling with two fingers,
and pointing with the index finger to move the cursor and pinch to click."""
from collections import deque
from math import copysign, dist

from .config import Config
from .gestures import Cooldown, Gesture, GestureEvent
from .hand_landmarks import Hand, HandLandmark
from .hand_poses import Pose, PoseConfirmer, PoseReader, palm_center, palm_position
from .pointer_gestures import PointerGestures

# Reversing the scroll direction takes this much extra travel, as a fraction of a
# scroll step, so hand jitter can't scroll back and forth.
SCROLL_REVERSAL_MARGIN = 0.5
# A fist that moves farther than this (frame widths, at the reference hand size) starts its hold
# over: a fist on the mouse or under the chin isn't a deliberate hold.
FIST_STILL_RADIUS = 0.05
# A hand first seen this close to an edge (fraction of the frame) is probably coming
# into view, so for EDGE_ENTRY_S it can't swipe away from that edge.
EDGE_MARGIN = 0.1
EDGE_ENTRY_S = 1.0


class OneHandGestures:
    """Call update() once per camera frame; it returns the gestures completed in that frame."""

    def __init__(self, config: Config, pointer_cutoff_hz: float):
        self.config = config
        self._pose_reader = PoseReader()
        self._pose = PoseConfirmer(config.pose_confirm_s)
        self._hand_last_seen_time = float("-inf")
        self._hand_in_view = False
        self._swipe_cooldown = Cooldown(config.cooldown_s, config.opposite_cooldown_s)
        self._swipes_blocked_after_entry: set[Gesture] = set()
        self._entry_time = float("-inf")
        self._pointer = PointerGestures(config.pinch_distance, config.double_pinch_s,
                                        pointer_cutoff_hz, config.pointer_responsiveness)
        self._reset_pose_tracking()

    @property
    def pose(self) -> Pose | None:
        """The confirmed pose; None while no hand is visible."""
        return self._pose.pose

    @property
    def pointer(self) -> PointerGestures:
        return self._pointer

    def _reset_pose_tracking(self):
        """Forget the current pose's progress; called when the pose changes or the hand is lost."""
        self._palm_path: deque[tuple[float, float, float]] = deque()  # (time, x, y)
        self._fist_start_time: float | None = None
        self._fist_start_palm: tuple[float, float] | None = None
        self._fist_hold_reported = False
        self._scroll_anchor_y: float | None = None
        self._last_scroll_steps = 0
        self._pointer.reset()

    def update(self, hand: Hand | None, now: float, scale: float = 1.0, paused: bool = False) -> list[GestureEvent]:
        """Process one frame: the hand (None if no hand), seen at `now` seconds.

        `scale` is the hand's size relative to the reference size (see HandScale): distances the
        hand must move are multiplied by it. While paused, poses are still tracked but no gestures
        are reported.
        """
        if hand is None:
            self._on_no_hand(now)
            return []
        if not self._hand_in_view:
            self._on_hand_appeared(hand, now)
        self._hand_last_seen_time = now
        seen_pose = self._pose_reader.read(hand)
        if self.pose is Pose.POINTING and self._pointer.holds_pinch(hand):
            seen_pose = Pose.POINTING  # a pinch often curls the index finger; it isn't a fist
        if self._pose.update(seen_pose, now):
            self._reset_pose_tracking()

        if paused:
            self._pointer.reset()
            return []
        if self.pose is Pose.FIST:
            return self._detect_fist_hold(hand, now, scale)
        if self.pose is Pose.OPEN_PALM:
            return self._detect_swipe(hand, now, scale)
        if self.pose is Pose.TWO_FINGERS and self.config.scroll_enabled:
            return self._detect_scroll(hand, scale)
        if self.pose is Pose.POINTING and self.config.pointer_enabled:
            return self._pointer.update(hand, now, scale)
        return []

    def _on_no_hand(self, now: float):
        # Motion blur can hide the hand for a frame or two mid-gesture; only give up after the grace period.
        if now - self._hand_last_seen_time >= self.config.hand_lost_grace_s:
            self._hand_in_view = False
            self._pose.reset()
            self._pose_reader.reset()
            self._reset_pose_tracking()

    def _on_hand_appeared(self, hand: Hand, now: float):
        self._hand_in_view = True
        self._entry_time = now
        self._swipes_blocked_after_entry = swipes_into_view(palm_center(hand.image))

    def _detect_fist_hold(self, hand: Hand, now: float, scale: float) -> list[GestureEvent]:
        palm = palm_position(hand)
        if self._fist_start_time is None or dist(palm, self._fist_start_palm) > FIST_STILL_RADIUS * scale:
            self._fist_start_time = now
            self._fist_start_palm = palm
        held_long_enough = now - self._fist_start_time >= self.config.fist_hold_s
        if held_long_enough and not self._fist_hold_reported:
            self._fist_hold_reported = True  # once per fist; open the hand to trigger it again
            return [GestureEvent(Gesture.FIST_HOLD)]
        return []

    def _detect_swipe(self, hand: Hand, now: float, scale: float) -> list[GestureEvent]:
        config = self.config
        x, y = palm_position(hand)
        path = self._palm_path
        path.append((now, x, y))
        while now - path[0][0] > config.swipe_window_s:
            path.popleft()

        _, start_x, start_y = path[0]
        dx, dy = x - start_x, y - start_y
        distance_x, distance_y = abs(dx), abs(dy)
        if max(distance_x, distance_y) < config.swipe_distance * scale:
            return []
        if distance_x >= distance_y * config.swipe_axis_ratio:
            swipe = Gesture.SWIPE_RIGHT if dx > 0 else Gesture.SWIPE_LEFT
        elif distance_y >= distance_x * config.swipe_axis_ratio:
            swipe = Gesture.SWIPE_DOWN if dy > 0 else Gesture.SWIPE_UP
        else:
            return []  # diagonal

        # Reported or not, this motion is used up: the next swipe has to start fresh.
        path.clear()
        path.append((now, x, y))
        coming_into_view = swipe in self._swipes_blocked_after_entry and now - self._entry_time < EDGE_ENTRY_S
        if coming_into_view or not self._swipe_cooldown.allows(swipe, now):
            return []
        self._swipe_cooldown.record(swipe, now)
        return [GestureEvent(swipe)]

    def _detect_scroll(self, hand: Hand, scale: float) -> list[GestureEvent]:
        fingertips_y = (hand.point(HandLandmark.INDEX_FINGER_TIP)[1]
                        + hand.point(HandLandmark.MIDDLE_FINGER_TIP)[1]) / 2
        if self._scroll_anchor_y is None:
            self._scroll_anchor_y = fingertips_y
            return []

        step_size = self.config.scroll_step * scale
        travel = self._scroll_anchor_y - fingertips_y  # hand moving up = positive
        is_reversing = travel * self._last_scroll_steps < 0
        if is_reversing:
            travel = copysign(max(abs(travel) - SCROLL_REVERSAL_MARGIN * step_size, 0), travel)
        steps = int(travel / step_size)
        if steps == 0:
            return []
        self._scroll_anchor_y -= steps * step_size
        self._last_scroll_steps = steps
        return [GestureEvent(Gesture.SCROLL, steps)]


def swipes_into_view(palm: tuple[float, float]) -> set[Gesture]:
    """The swipes a hand first seen at `palm` (fractions of the frame) would make just by coming
    into view from a nearby edge."""
    x, y = palm
    swipes = set()
    if x < EDGE_MARGIN:
        swipes.add(Gesture.SWIPE_RIGHT)
    if x > 1 - EDGE_MARGIN:
        swipes.add(Gesture.SWIPE_LEFT)
    if y < EDGE_MARGIN:
        swipes.add(Gesture.SWIPE_DOWN)
    if y > 1 - EDGE_MARGIN:
        swipes.add(Gesture.SWIPE_UP)
    return swipes
