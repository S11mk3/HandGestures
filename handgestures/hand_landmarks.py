"""The 21 points MediaPipe reports for a hand, and a hand as seen in one frame.

Finger joints from the palm out: MCP (knuckle), PIP (middle joint), DIP (last joint), TIP.
"""
from dataclasses import dataclass
from enum import IntEnum

# One hand: 21 (x, y, z) points, in HandLandmark order.
Landmarks = list[tuple[float, float, float]]


class HandLandmark(IntEnum):
    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_FINGER_MCP = 5
    INDEX_FINGER_PIP = 6
    INDEX_FINGER_DIP = 7
    INDEX_FINGER_TIP = 8
    MIDDLE_FINGER_MCP = 9
    MIDDLE_FINGER_PIP = 10
    MIDDLE_FINGER_DIP = 11
    MIDDLE_FINGER_TIP = 12
    RING_FINGER_MCP = 13
    RING_FINGER_PIP = 14
    RING_FINGER_DIP = 15
    RING_FINGER_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20


# Pairs of landmarks joined by a bone, for drawing the hand.
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
]


@dataclass(frozen=True)
class Hand:
    """One hand in one frame.

    `image` places the hand in the frame: x and y are fractions of the frame's width and height
    (the frame is mirrored, so x grows toward the user's right; y grows downward).
    `world` is its true 3D shape in meters, whatever its distance or angle to the camera:
    what to use for judging finger bends and gaps.
    """
    image: Landmarks
    world: Landmarks
    aspect: float = 0.75  # the frame's height / width
    handedness: str = ""  # "Left" or "Right"
    score: float = 1.0  # how sure MediaPipe is of the handedness, 0-1

    def point(self, landmark: int) -> tuple[float, float]:
        """Where a landmark is, in frame widths along both axes, so distances compare alike in any direction."""
        x, y, _ = self.image[landmark]
        return x, y * self.aspect
