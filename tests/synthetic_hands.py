"""Synthetic hands for tests: landmarks for a pose at a position, and a simulator that
feeds them to a GestureDetector frame by frame."""
from math import cos, radians, sin

from handgestures.config import Config
from handgestures.gesture_detector import GestureDetector
from handgestures.gestures import GestureEvent
from handgestures.hand_poses import Pose

FPS = 30
FRAME_INTERVAL_S = 1 / FPS

# Offsets from the wrist for an upright right hand, fingers pointing up (-y),
# keyed by landmark index (see handgestures/hand_landmarks.py).
THUMB_OFFSETS = {1: (-0.05, -0.04), 2: (-0.09, -0.07), 3: (-0.12, -0.10), 4: (-0.14, -0.13)}
MCP_OFFSETS = {5: (-0.06, -0.15), 9: (-0.02, -0.16), 13: (0.02, -0.15), 17: (0.06, -0.13)}
PIP_OFFSETS = {6: (-0.07, -0.22), 10: (-0.02, -0.24), 14: (0.03, -0.22), 18: (0.07, -0.19)}
TIP_OFFSETS_EXTENDED = {8: (-0.08, -0.32), 12: (-0.02, -0.35), 16: (0.04, -0.32), 20: (0.09, -0.27)}
TIP_OFFSETS_CURLED = {8: (-0.05, -0.11), 12: (-0.02, -0.11), 16: (0.02, -0.10), 20: (0.05, -0.09)}
FINGERS = ((6, 8), (10, 12), (14, 16), (18, 20))  # (PIP, TIP) for index, middle, ring, pinky

# Which of index, middle, ring and pinky are extended in each pose.
EXTENDED_FINGERS_BY_POSE = {
    Pose.OPEN_PALM: (True, True, True, True),
    Pose.FIST: (False, False, False, False),
    Pose.TWO_FINGERS: (True, True, False, False),
    Pose.OTHER: (True, False, False, False),
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


def make_hand(pose: Pose, wrist_x=0.5, wrist_y=0.8, rotation: tuple[str, float] | None = None):
    """Landmarks of a synthetic hand in the given pose. `rotation` = (axis, degrees) turns the hand in 3D."""
    offsets = {0: (0.0, 0.0), **THUMB_OFFSETS, **MCP_OFFSETS, **PIP_OFFSETS}
    for is_extended, (pip, tip) in zip(EXTENDED_FINGERS_BY_POSE[pose], FINGERS):
        offsets[tip] = (TIP_OFFSETS_EXTENDED if is_extended else TIP_OFFSETS_CURLED)[tip]
        dip = pip + 1
        offsets[dip] = tuple((a + b) / 2 for a, b in zip(offsets[pip], offsets[tip]))

    points = [(offsets[i][0], offsets[i][1], 0.0) for i in range(21)]
    if rotation:
        points = [rotate(point, *rotation) for point in points]
    # The camera sees the hand flattened onto the image.
    return [(wrist_x + x, wrist_y + y, 0.0) for x, y, _ in points]


class HandSimulator:
    """Feeds a GestureDetector synthetic frames at FPS."""

    def __init__(self):
        self.detector = GestureDetector(Config())
        self.time = 0.0

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
            hands = [make_hand(seen_pose, x, y)] if seen_pose else []
            if i in phantom_frames:
                hands = sorted(hands + [make_hand(pose, x + 0.04, y + 0.03)], key=lambda hand: hand[0][0])
            events += self.detector.update(hands, self.time, paused)
            self.time += FRAME_INTERVAL_S
        return events

    def hold(self, pose, frames, at=(0.5, 0.8), paused=False) -> list[GestureEvent]:
        return self.move(pose, at, at, frames, paused)

    def no_hand(self, seconds) -> list[GestureEvent]:
        events = []
        for _ in range(round(seconds * FPS)):
            events += self.detector.update([], self.time)
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
                hands.append(make_hand(pose, x, y))
            if i in one_hand_frames:
                hands = hands[1:]
            events += self.detector.update(hands, self.time)
            self.time += FRAME_INTERVAL_S
        return events

    def hold_two_hands(self, left_at, right_at, frames, pose=Pose.OPEN_PALM) -> list[GestureEvent]:
        return self.move_two_hands((left_at, left_at), (right_at, right_at), frames, pose)
