"""Turns each frame's hands into gesture events, routing them to the one- or two-hand gestures."""
from math import dist

from .config import Config
from .gestures import GestureEvent
from .hand_landmarks import Landmarks
from .hand_poses import palm_center
from .one_hand_gestures import OneHandGestures
from .two_hand_gestures import TwoHandGestures


class GestureDetector:
    """Call update() once per camera frame; it returns the gestures completed in that frame."""

    def __init__(self, config: Config):
        self.config = config
        self._one_hand = OneHandGestures(config)
        self._two_hands = TwoHandGestures(config)
        self._two_hand_mode = False
        self._two_hands_seen_since: float | None = None
        self._two_hands_last_seen_time = float("-inf")
        self._followed_palm: tuple[float, float] | None = None

    @property
    def pose_label(self) -> str:
        """What the detector sees, for the preview: e.g. "fist" or "open palm + open palm"."""
        if self._two_hand_mode:
            return " + ".join(pose.value if pose else "?" for pose in self._two_hands.poses)
        if self._one_hand.is_pinched:
            return "pinch"
        pose = self._one_hand.pose
        return pose.value if pose else "no hand"

    @property
    def pointer_position(self) -> tuple[float, float] | None:
        """Where the pointing fingertip puts the pointer, in fractions of the frame; None while not pointing."""
        return None if self._two_hand_mode else self._one_hand.pointer_position

    def update(self, hands: list[Landmarks], now: float, paused: bool = False) -> list[GestureEvent]:
        """Process one frame: the hands seen (none, one, or two ordered left to right) at `now` seconds.

        While paused, poses are still tracked but no gestures are reported.
        """
        self._update_two_hand_mode(len(hands) >= 2, now)
        if self._two_hand_mode:
            # Each hand moving apart looks like a swipe on its own: one-hand gestures wait.
            self._one_hand.update(None, now)
            both_hands = (hands[0], hands[-1]) if len(hands) >= 2 else None
            return self._two_hands.update(both_hands, now, paused)

        self._two_hands.update(None, now)
        # A hand being lowered after a two-hand gesture is still moving; don't read it as a swipe.
        in_holdoff = now - self._two_hands_last_seen_time < self.config.two_hand_holdoff_s
        return self._one_hand.update(self._followed_hand(hands), now, paused or in_holdoff)

    def _update_two_hand_mode(self, two_hands_seen: bool, now: float):
        """Two-hand mode starts once two hands have been seen for pose_confirm_s, and ends
        after hand_lost_grace_s without them.

        MediaPipe sometimes reports one hand twice, or a small phantom hand, for a frame
        or two; requiring a steady second hand keeps those from interrupting one-hand gestures.
        """
        if not two_hands_seen:
            self._two_hands_seen_since = None
            if self._two_hand_mode and now - self._two_hands_last_seen_time >= self.config.hand_lost_grace_s:
                self._two_hand_mode = False
            return
        if self._two_hands_seen_since is None:
            self._two_hands_seen_since = now
        if now - self._two_hands_seen_since >= self.config.pose_confirm_s:
            self._two_hand_mode = True
        if self._two_hand_mode:
            self._two_hands_last_seen_time = now

    def _followed_hand(self, hands: list[Landmarks]) -> Landmarks | None:
        """The hand one-hand gestures follow: when a second hand shows up briefly, the one
        nearest the last position, since the other is usually the same hand reported twice."""
        if not hands:
            return None
        if self._followed_palm is None:
            hand = hands[0]
        else:
            hand = min(hands, key=lambda candidate: dist(palm_center(candidate), self._followed_palm))
        self._followed_palm = palm_center(hand)
        return hand
