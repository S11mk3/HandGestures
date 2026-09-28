"""Reading a hand's pose (open palm, fist, ...) from its landmarks.

Frames are mirrored before tracking, so x grows toward the user's right; y grows downward.
"""
from enum import Enum
from math import dist

from .hand_landmarks import HandLandmark, Landmarks

PALM_POINTS = (
    HandLandmark.WRIST,
    HandLandmark.INDEX_FINGER_MCP,
    HandLandmark.MIDDLE_FINGER_MCP,
    HandLandmark.RING_FINGER_MCP,
    HandLandmark.PINKY_MCP,
)
# (middle joint, tip) of each finger. The thumb is left out: it doesn't fold toward the wrist.
FINGERS = (
    (HandLandmark.INDEX_FINGER_PIP, HandLandmark.INDEX_FINGER_TIP),
    (HandLandmark.MIDDLE_FINGER_PIP, HandLandmark.MIDDLE_FINGER_TIP),
    (HandLandmark.RING_FINGER_PIP, HandLandmark.RING_FINGER_TIP),
    (HandLandmark.PINKY_PIP, HandLandmark.PINKY_TIP),
)


class Pose(Enum):
    OPEN_PALM = "open palm"
    FIST = "fist"
    TWO_FINGERS = "two fingers"
    OTHER = "other"


def extended_fingers(landmarks: Landmarks) -> list[bool]:
    """For index, middle, ring and pinky: is the finger stretched out?

    A finger is stretched out when its tip is farther from the wrist than its middle joint.
    """
    wrist = landmarks[HandLandmark.WRIST][:2]
    return [
        dist(landmarks[tip][:2], wrist) > dist(landmarks[middle_joint][:2], wrist)
        for middle_joint, tip in FINGERS
    ]


def classify_pose(landmarks: Landmarks) -> Pose:
    extended = extended_fingers(landmarks)
    if all(extended):
        return Pose.OPEN_PALM
    if not any(extended):
        return Pose.FIST
    if extended == [True, True, False, False]:
        return Pose.TWO_FINGERS
    return Pose.OTHER


def palm_center(landmarks: Landmarks) -> tuple[float, float]:
    xs = [landmarks[point][0] for point in PALM_POINTS]
    ys = [landmarks[point][1] for point in PALM_POINTS]
    return sum(xs) / len(xs), sum(ys) / len(ys)


class PoseConfirmer:
    """One hand's pose, which switches only once a newly seen pose has held for confirm_s.

    Until then frames keep counting as the current pose, so one misread frame changes nothing.
    """

    def __init__(self, confirm_s: float):
        self._confirm_s = confirm_s
        self.pose: Pose | None = None  # None until a pose is confirmed
        self._unconfirmed_pose: Pose | None = None
        self._unconfirmed_pose_since = 0.0

    def update(self, seen_pose: Pose, now: float) -> bool:
        """Feed the pose seen in this frame. Return True if the confirmed pose changed."""
        if seen_pose == self.pose:
            self._unconfirmed_pose = None
            return False
        if seen_pose != self._unconfirmed_pose:
            self._unconfirmed_pose = seen_pose
            self._unconfirmed_pose_since = now
        if now - self._unconfirmed_pose_since < self._confirm_s:
            return False
        self.pose = seen_pose
        self._unconfirmed_pose = None
        return True

    def reset(self):
        self.pose = None
        self._unconfirmed_pose = None
