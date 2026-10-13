from math import cos, dist, radians, sin

import pytest

from handgestures.hand_landmarks import Hand
from handgestures.hand_poses import (
    REFERENCE_PALM_LENGTH,
    HandScale,
    Pose,
    PoseReader,
    finger_bends,
    palm_length_in_frame,
)

from synthetic_hands import make_hand


@pytest.mark.parametrize("pose", list(Pose))
def test_reads_each_pose(pose):
    assert PoseReader().read(make_hand(pose)) is pose


@pytest.mark.parametrize("axis", ["x", "y", "z"])
@pytest.mark.parametrize("pose", list(Pose))
def test_pose_is_read_the_same_when_the_hand_is_turned(pose, axis):
    # The 2D tip-vs-joint check this replaced failed when the hand was tilted toward the camera.
    assert PoseReader().read(make_hand(pose, rotation=(axis, 60))) is pose


def test_straight_and_curled_fingers_bend_as_expected():
    open_bends = finger_bends(make_hand(Pose.OPEN_PALM).world)
    fist_bends = finger_bends(make_hand(Pose.FIST).world)
    assert all(bend < 20 for bend in open_bends)
    assert all(bend > 120 for bend in fist_bends)


def bend_pinky(hand: Hand, degrees: float) -> Hand:
    """The hand with its pinky bent toward the camera by `degrees` in total, half at each joint."""
    world = list(hand.world)
    mcp, pip, dip, tip = (world[i] for i in (17, 18, 19, 20))
    along = [b - a for a, b in zip(mcp, pip)]
    length = sum(v * v for v in along) ** 0.5
    along = [v / length for v in along]
    toward_camera = (0.0, 0.0, -1.0)  # perpendicular to the flat synthetic finger

    def direction(angle):
        return [cos(radians(angle)) * a + sin(radians(angle)) * t for a, t in zip(along, toward_camera)]

    middle_length, last_length = dist(pip, dip), dist(dip, tip)
    world[19] = tuple(p + middle_length * d for p, d in zip(pip, direction(degrees / 2)))
    world[20] = tuple(p + last_length * d for p, d in zip(world[19], direction(degrees)))
    return Hand(image=hand.image, world=world, aspect=hand.aspect)


def test_half_bent_finger_keeps_its_previous_state():
    half_bent = bend_pinky(make_hand(Pose.OPEN_PALM), 85)  # inside the hysteresis band
    assert finger_bends(half_bent.world)[3] == pytest.approx(85)
    stretched_first = PoseReader()
    assert stretched_first.read(make_hand(Pose.OPEN_PALM)) is Pose.OPEN_PALM
    assert stretched_first.read(half_bent) is Pose.OPEN_PALM
    curled_first = PoseReader()
    assert curled_first.read(make_hand(Pose.POINTING)) is Pose.POINTING  # pinky curled
    assert curled_first.read(bend_pinky(make_hand(Pose.POINTING), 85)) is Pose.POINTING
    # Past the band, the finger switches.
    assert stretched_first.read(bend_pinky(make_hand(Pose.OPEN_PALM), 110)) is Pose.OTHER


@pytest.mark.parametrize("rotation", [None, ("x", 55), ("y", 55), ("z", 40)])
def test_palm_length_ignores_tilt(rotation):
    hand = make_hand(Pose.OPEN_PALM, rotation=rotation)
    assert palm_length_in_frame(hand) == pytest.approx(REFERENCE_PALM_LENGTH, rel=0.05)


def test_hand_scale_follows_hand_size_slowly():
    scale = HandScale()
    assert scale.factor == pytest.approx(1.0)
    far_hand = make_hand(Pose.OPEN_PALM, palm_length=REFERENCE_PALM_LENGTH / 2)
    scale.update(far_hand, 0.0)  # the first sighting counts fully...
    scale.update(far_hand, 0.1)
    assert scale.factor == pytest.approx(0.5, rel=0.1)
    near_hand = make_hand(Pose.OPEN_PALM, palm_length=REFERENCE_PALM_LENGTH * 2)
    scale.update(near_hand, 0.2)  # ...later ones only nudge it
    assert 0.5 < scale.factor < 0.8
