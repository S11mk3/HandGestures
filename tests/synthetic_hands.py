"""Synthetic hands for tests: a Hand in a given pose and position, and a simulator that feeds
hands to a GestureDetector frame by frame."""
from math import cos, hypot, radians, sin

from handgestures.config import Config
from handgestures.gesture_detector import GestureDetector
from handgestures.gestures import GestureEvent
from handgestures.hand_landmarks import Hand
from handgestures.hand_poses import REFERENCE_PALM_LENGTH, Pose

FPS = 30
FRAME_INTERVAL_S = 1 / FPS
ASPECT = 0.75  # a 640x480 frame
PALM_LENGTH_M = 0.09  # an adult's wrist to middle knuckle

# Offsets from the wrist for an upright right hand facing the camera, fingers pointing up (-y),
# keyed by landmark index (see handgestures/hand_landmarks.py). Units: _UNIT is one palm length.
_UNIT = hypot(0.02, 0.16)
THUMB = {1: (-0.05, -0.04), 2: (-0.09, -0.07), 3: (-0.12, -0.10), 4: (-0.14, -0.13)}
MCP = {5: (-0.06, -0.15), 9: (-0.02, -0.16), 13: (0.02, -0.15), 17: (0.06, -0.13)}
PIP = {6: (-0.07, -0.22), 10: (-0.02, -0.24), 14: (0.03, -0.22), 18: (0.07, -0.19)}
TIP_EXTENDED = {8: (-0.08, -0.32), 12: (-0.02, -0.35), 16: (0.04, -0.32), 20: (0.09, -0.27)}
TIP_CURLED = {8: (-0.05, -0.11), 12: (-0.02, -0.11), 16: (0.02, -0.10), 20: (0.05, -0.09)}
FINGERS = ((6, 8), (10, 12), (14, 16), (18, 20))  # (PIP, TIP) for index, middle, ring, pinky

# Which of index, middle, ring and pinky are stretched out in each pose.
EXTENDED_FINGERS_BY_POSE = {
    Pose.OPEN_PALM: (True, True, True, True),
    Pose.FIST: (False, False, False, False),
    Pose.TWO_FINGERS: (True, True, False, False),
    Pose.POINTING: (True, False, False, False),
    Pose.OTHER: (True, False, False, True),
}


def rotate(point, axis: str, degrees: float):
    """Rotate a 3D point around the x, y or z axis."""
    x, y, z = point
    c, s = cos(radians(degrees)), sin(radians(degrees))
    if axis == "x":
        return x, y * c - z * s, y * s + z * c
    if axis == "y":
        return x * c + z * s, y, -x * s + z * c
    return x * c - y * s, x * s + y * c, z


def make_hand(pose: Pose, wrist_x=0.5, wrist_y=0.8, rotation: tuple[str, float] | None = None,
              palm_length=REFERENCE_PALM_LENGTH, pinch_gap: float | None = None) -> Hand:
    """A synthetic hand in the given pose, its wrist at (wrist_x, wrist_y) in fractions of the frame.

    `rotation` = (axis, degrees) turns the hand in 3D. `palm_length` (frame widths) sets how big it
    looks, i.e. how near the camera it is. `pinch_gap` puts the thumb tip that far from the index
    tip, in palm lengths.
    """
    offsets = {0: (0.0, 0.0, 0.0)}
    for landmarks in (THUMB, MCP, PIP):
        offsets.update({i: (x, y, 0.0) for i, (x, y) in landmarks.items()})
    for is_extended, (pip, tip) in zip(EXTENDED_FINGERS_BY_POSE[pose], FINGERS):
        tip_x, tip_y = (TIP_EXTENDED if is_extended else TIP_CURLED)[tip]
        pip_x, pip_y, _ = offsets[pip]
        # A curled finger folds toward the camera (-z); a straight one stays flat.
        offsets[pip + 1] = ((pip_x + tip_x) / 2, (pip_y + tip_y) / 2, 0.0 if is_extended else -0.06)
        offsets[tip] = (tip_x, tip_y, 0.0 if is_extended else -0.05)
    if pinch_gap is not None:
        index_x, index_y, index_z = offsets[8]
        offsets[4] = (index_x + pinch_gap * _UNIT, index_y, index_z)

    points = [tuple(value / _UNIT for value in offsets[i]) for i in range(21)]  # in palm lengths
    if rotation:
        points = [rotate(point, *rotation) for point in points]
    world = [(x * PALM_LENGTH_M, y * PALM_LENGTH_M, z * PALM_LENGTH_M) for x, y, z in points]
    # The camera sees the hand flattened onto the image.
    image = [(wrist_x + x * palm_length, wrist_y + y * palm_length / ASPECT, z * palm_length) for x, y, z in points]
    return Hand(image=image, world=world, aspect=ASPECT, handedness="Right", score=0.9)


class HandSimulator:
    """Feeds a GestureDetector synthetic frames at FPS. `palm_length` sets how big the hands look."""

    def __init__(self, config: Config | None = None, palm_length=REFERENCE_PALM_LENGTH):
        self.detector = GestureDetector(config or Config())
        self.palm_length = palm_length
        self.scale = palm_length / REFERENCE_PALM_LENGTH
        self.time = 0.0

    def hand(self, pose, x, y, **kwargs) -> Hand:
        return make_hand(pose, x, y, palm_length=self.palm_length, **kwargs)

    def move(self, pose, start, end, frames, paused=False, misread=None, phantom_frames=()) -> list[GestureEvent]:
        """Move the wrist linearly from start to end over the given frames; return all events.

        `misread` maps frame numbers to the pose the tracker reports instead, or to None for no hand.
        In `phantom_frames` the tracker also reports a second copy of the hand, as MediaPipe sometimes does.
        """
        misread = misread or {}
        events = []
        for i in range(frames):
            progress = i / max(frames - 1, 1)
            x = start[0] + (end[0] - start[0]) * progress
            y = start[1] + (end[1] - start[1]) * progress
            seen_pose = misread.get(i, pose)
            hands = [self.hand(seen_pose, x, y)] if seen_pose else []
            if i in phantom_frames:
                hands = sorted(hands + [self.hand(pose, x + 0.04, y + 0.03)], key=lambda hand: hand.image[0][0])
            events += self.detector.update(hands, self.time, self.scale, paused)
            self.time += FRAME_INTERVAL_S
        return events

    def hold(self, pose, frames, at=(0.5, 0.8), paused=False) -> list[GestureEvent]:
        return self.move(pose, at, at, frames, paused)

    def no_hand(self, seconds) -> list[GestureEvent]:
        events = []
        for _ in range(round(seconds * FPS)):
            events += self.detector.update([], self.time, self.scale)
            self.time += FRAME_INTERVAL_S
        return events

    def move_two_hands(self, left, right, frames, pose=Pose.OPEN_PALM, one_hand_frames=()) -> list[GestureEvent]:
        """Move both wrists linearly, each from its (start, end), over the given frames; return all events.

        In `one_hand_frames` (frame numbers) the tracker reports only the right hand.
        """
        events = []
        for i in range(frames):
            progress = i / max(frames - 1, 1)
            hands = []
            for (start_x, start_y), (end_x, end_y) in (left, right):
                x = start_x + (end_x - start_x) * progress
                y = start_y + (end_y - start_y) * progress
                hands.append(self.hand(pose, x, y))
            if i in one_hand_frames:
                hands = hands[1:]
            events += self.detector.update(hands, self.time, self.scale)
            self.time += FRAME_INTERVAL_S
        return events

    def hold_two_hands(self, left_at, right_at, frames, pose=Pose.OPEN_PALM) -> list[GestureEvent]:
        return self.move_two_hands((left_at, left_at), (right_at, right_at), frames, pose)
