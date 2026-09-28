"""Gestures made with two open palms: moving them apart or together."""
from collections import deque

from .config import Config
from .gestures import Cooldown, Gesture, GestureEvent
from .hand_landmarks import Landmarks
from .hand_poses import Pose, PoseConfirmer, classify_pose, palm_center

# Each hand must supply at least this share of the change in the gap between them,
# so one hand swiping beside a still one doesn't count.
TWO_HAND_MIN_SHARE = 0.3


class TwoHandGestures:
    """Call update() once per camera frame with both hands (left first), or None when they aren't both visible."""

    def __init__(self, config: Config):
        self.config = config
        self._left_pose = PoseConfirmer(config.pose_confirm_s)
        self._right_pose = PoseConfirmer(config.pose_confirm_s)
        self._hands_last_seen_time = float("-inf")
        self._cooldown = Cooldown(config)
        self._palm_path: deque[tuple[float, float, float]] = deque()  # (time, left palm x, right palm x)

    @property
    def poses(self) -> tuple[Pose | None, Pose | None]:
        """The confirmed (left, right) poses."""
        return self._left_pose.pose, self._right_pose.pose

    def update(self, hands: tuple[Landmarks, Landmarks] | None, now: float,
               paused: bool = False) -> list[GestureEvent]:
        if hands is None:
            # A hand hidden for a frame or two (motion blur) doesn't end the gesture.
            if now - self._hands_last_seen_time >= self.config.hand_lost_grace_s:
                self._left_pose.reset()
                self._right_pose.reset()
                self._palm_path.clear()
            return []
        self._hands_last_seen_time = now

        left, right = hands
        left_pose_changed = self._left_pose.update(classify_pose(left), now)
        right_pose_changed = self._right_pose.update(classify_pose(right), now)
        if left_pose_changed or right_pose_changed:
            self._palm_path.clear()  # the gesture starts once both palms are confirmed open
        if paused or self.poses != (Pose.OPEN_PALM, Pose.OPEN_PALM):
            self._palm_path.clear()
            return []
        return self._detect_gap_change(palm_center(left)[0], palm_center(right)[0], now)

    def _detect_gap_change(self, left_x: float, right_x: float, now: float) -> list[GestureEvent]:
        path = self._palm_path
        path.append((now, left_x, right_x))
        while now - path[0][0] > self.config.two_hand_window_s:
            path.popleft()

        _, start_left_x, start_right_x = path[0]
        left_hand_moved = left_x - start_left_x  # positive = toward the right
        right_hand_moved = right_x - start_right_x
        gap_change = right_hand_moved - left_hand_moved  # positive = apart
        if abs(gap_change) < self.config.two_hand_distance:
            return []

        # Moving apart, the left hand goes left and the right hand goes right; together, the reverse.
        apart = gap_change > 0
        left_share = (-left_hand_moved if apart else left_hand_moved) / abs(gap_change)
        right_share = (right_hand_moved if apart else -right_hand_moved) / abs(gap_change)
        if min(left_share, right_share) < TWO_HAND_MIN_SHARE:
            return []

        gesture = Gesture.HANDS_APART if apart else Gesture.HANDS_TOGETHER
        # Reported or not, this motion is used up: the next gesture has to start fresh.
        path.clear()
        path.append((now, left_x, right_x))
        if not self._cooldown.allows(gesture, now):
            return []
        self._cooldown.record(gesture, now)
        return [GestureEvent(gesture)]
