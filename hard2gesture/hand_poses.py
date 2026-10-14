"""Reading a hand's pose (open palm, fist, ...) and its size in the frame from its landmarks."""
from enum import Enum
from math import acos, degrees, dist, exp

from .hand_landmarks import Hand, HandLandmark, Landmarks

PALM_POINTS = (
    HandLandmark.WRIST,
    HandLandmark.INDEX_FINGER_MCP,
    HandLandmark.MIDDLE_FINGER_MCP,
    HandLandmark.RING_FINGER_MCP,
    HandLandmark.PINKY_MCP,
)
# (knuckle, middle joint, last joint, tip) of each finger. The thumb is left out: it doesn't fold toward the wrist.
FINGERS = (
    (HandLandmark.INDEX_FINGER_MCP, HandLandmark.INDEX_FINGER_PIP,
     HandLandmark.INDEX_FINGER_DIP, HandLandmark.INDEX_FINGER_TIP),
    (HandLandmark.MIDDLE_FINGER_MCP, HandLandmark.MIDDLE_FINGER_PIP,
     HandLandmark.MIDDLE_FINGER_DIP, HandLandmark.MIDDLE_FINGER_TIP),
    (HandLandmark.RING_FINGER_MCP, HandLandmark.RING_FINGER_PIP,
     HandLandmark.RING_FINGER_DIP, HandLandmark.RING_FINGER_TIP),
    (HandLandmark.PINKY_MCP, HandLandmark.PINKY_PIP, HandLandmark.PINKY_DIP, HandLandmark.PINKY_TIP),
)
# A finger counts as stretched out once it bends less than EXTENDED_MAX_BEND degrees in total at
# its middle and last joints, and as curled once it bends more than CURLED_MIN_BEND. In between it
# keeps its previous state, so a half-bent finger doesn't flicker between the two.
EXTENDED_MAX_BEND = 70.0
CURLED_MIN_BEND = 100.0

# Palm length (wrist to middle knuckle) in frame widths of a hand about 60 cm from a typical
# laptop webcam: the hand size the distance settings are tuned for.
REFERENCE_PALM_LENGTH = 0.13


class Pose(Enum):
    OPEN_PALM = "open palm"
    FIST = "fist"
    TWO_FINGERS = "two fingers"
    POINTING = "pointing"
    OTHER = "other"


def finger_bends(world: Landmarks) -> list[float]:
    """For index, middle, ring and pinky: how many degrees the finger bends at its middle and last joints.

    0 for a straight finger; about 150 or more for one curled into a fist. Uses the 3D shape,
    so it reads the same whichever way the hand is turned.
    """
    return [_bend(world[knuckle], world[middle], world[last]) + _bend(world[middle], world[last], world[tip])
            for knuckle, middle, last, tip in FINGERS]


def _bend(a, b, c) -> float:
    """Degrees the path a -> b -> c turns at b: 0 when straight."""
    first = [q - p for p, q in zip(a, b)]
    second = [q - p for p, q in zip(b, c)]
    lengths = dist(a, b) * dist(b, c)
    if lengths == 0:
        return 0.0
    cosine = sum(p * q for p, q in zip(first, second)) / lengths
    return degrees(acos(max(-1.0, min(1.0, cosine))))


def classify_pose(extended: list[bool]) -> Pose:
    """The pose for which of index, middle, ring and pinky are stretched out."""
    if all(extended):
        return Pose.OPEN_PALM
    if not any(extended):
        return Pose.FIST
    if extended == [True, True, False, False]:
        return Pose.TWO_FINGERS
    if extended == [True, False, False, False]:
        return Pose.POINTING
    return Pose.OTHER


class PoseReader:
    """Reads one hand's pose each frame, remembering which fingers were stretched out for the hysteresis."""

    def __init__(self):
        self._extended: list[bool] | None = None

    def read(self, hand: Hand) -> Pose:
        bends = finger_bends(hand.world)
        if self._extended is None:
            middle = (EXTENDED_MAX_BEND + CURLED_MIN_BEND) / 2
            self._extended = [bend < middle for bend in bends]
        else:
            self._extended = [
                True if bend < EXTENDED_MAX_BEND else False if bend > CURLED_MIN_BEND else was_extended
                for bend, was_extended in zip(bends, self._extended)
            ]
        return classify_pose(self._extended)

    def reset(self):
        self._extended = None


def palm_center(landmarks: Landmarks) -> tuple[float, float]:
    """The middle of the palm, in the landmarks' own coordinates."""
    xs = [landmarks[point][0] for point in PALM_POINTS]
    ys = [landmarks[point][1] for point in PALM_POINTS]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def palm_position(hand: Hand) -> tuple[float, float]:
    """The middle of the palm, in frame widths along both axes."""
    x, y = palm_center(hand.image)
    return x, y * hand.aspect


def palm_length_in_frame(hand: Hand) -> float:
    """The palm's length (wrist to middle knuckle) in frame widths, as if it faced the camera squarely.

    Tilting the hand shortens either its length or its width in the image, rarely both, so this
    uses whichever is shortened less, converting the width with the hand's true 3D proportions.
    """
    length = dist(hand.point(HandLandmark.WRIST), hand.point(HandLandmark.MIDDLE_FINGER_MCP))
    width = dist(hand.point(HandLandmark.INDEX_FINGER_MCP), hand.point(HandLandmark.PINKY_MCP))
    world = hand.world
    true_length = dist(world[HandLandmark.WRIST], world[HandLandmark.MIDDLE_FINGER_MCP])
    true_width = dist(world[HandLandmark.INDEX_FINGER_MCP], world[HandLandmark.PINKY_MCP])
    if true_width <= 0:
        return length
    return max(length, width * true_length / true_width)


class HandScale:
    """How big hands look, relative to the size the distance settings are tuned for.

    `factor` is 1 at that size and 0.5 for a hand twice as far away; distances a hand must move
    are multiplied by it. It follows the hand's size slowly, so one misread frame barely moves it.
    """

    SMOOTHING_S = 1.0
    MIN_FACTOR = 0.35
    MAX_FACTOR = 3.0

    def __init__(self, palm_length: float = REFERENCE_PALM_LENGTH):
        self.palm_length = palm_length
        self._last_update: float | None = None

    @property
    def factor(self) -> float:
        return min(max(self.palm_length / REFERENCE_PALM_LENGTH, self.MIN_FACTOR), self.MAX_FACTOR)

    def update(self, hand: Hand, now: float):
        """Follow the hand's size. The first hand seen counts fully: calibration's guess was only a start."""
        elapsed = float("inf") if self._last_update is None else max(now - self._last_update, 0)
        weight = 1 - exp(-elapsed / self.SMOOTHING_S)
        self._last_update = now
        self.palm_length += weight * (palm_length_in_frame(hand) - self.palm_length)


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
