import pytest

from handgestures.gestures import Gesture, GestureEvent
from handgestures.hand_poses import Pose, classify_pose
from handgestures.one_hand_gestures import swipes_into_view
from synthetic_hands import HandSimulator, make_hand


@pytest.mark.parametrize("pose", list(Pose))
def test_classify_pose(pose):
    assert classify_pose(make_hand(pose)) is pose


@pytest.mark.parametrize("axis", ["x", "y", "z"])
@pytest.mark.parametrize("pose", list(Pose))
def test_pose_is_read_the_same_when_hand_is_turned(pose, axis):
    assert classify_pose(make_hand(pose, rotation=(axis, 60))) is pose


@pytest.mark.parametrize(
    "start,end,gesture",
    [
        ((0.5, 0.5), (0.5, 0.85), Gesture.SWIPE_DOWN),
        ((0.5, 0.85), (0.5, 0.5), Gesture.SWIPE_UP),
        ((0.7, 0.7), (0.3, 0.7), Gesture.SWIPE_LEFT),
        ((0.3, 0.7), (0.7, 0.7), Gesture.SWIPE_RIGHT),
    ],
)
def test_swipe_directions(start, end, gesture):
    hand = HandSimulator()
    hand.hold(Pose.OPEN_PALM, 5, at=start)
    assert hand.move(Pose.OPEN_PALM, start, end, 8) == [GestureEvent(gesture)]


def test_slow_drift_is_not_a_swipe():
    hand = HandSimulator()
    assert hand.move(Pose.OPEN_PALM, (0.3, 0.7), (0.7, 0.7), 90) == []


def test_diagonal_is_not_a_swipe():
    hand = HandSimulator()
    hand.hold(Pose.OPEN_PALM, 5, at=(0.3, 0.5))
    assert hand.move(Pose.OPEN_PALM, (0.3, 0.5), (0.6, 0.8), 8) == []


def test_unconfirmed_pose_does_not_swipe():
    hand = HandSimulator()
    # The hand appears already moving: until the pose is confirmed its travel doesn't count,
    # leaving too little to be a swipe.
    assert hand.move(Pose.OPEN_PALM, (0.3, 0.7), (0.52, 0.7), 5) == []


def test_one_misread_frame_does_not_cancel_swipe():
    hand = HandSimulator()
    hand.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7))
    events = hand.move(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8, misread={3: Pose.OTHER})
    assert events == [GestureEvent(Gesture.SWIPE_LEFT)]


def test_brief_hand_dropout_does_not_cancel_swipe():
    hand = HandSimulator()
    hand.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7))
    events = hand.move(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8, misread={3: None, 4: None})
    assert events == [GestureEvent(Gesture.SWIPE_LEFT)]


def test_hand_is_forgotten_only_after_grace_period():
    hand = HandSimulator()
    hand.hold(Pose.FIST, 10)
    hand.no_hand(0.1)
    assert hand.detector.pose_label == "fist"
    hand.no_hand(0.2)
    assert hand.detector.pose_label == "no hand"


def test_return_stroke_does_not_swipe_back():
    hand = HandSimulator()
    hand.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7))
    assert hand.move(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8) == [GestureEvent(Gesture.SWIPE_LEFT)]
    # Bring the hand back quickly to where it started.
    assert hand.move(Pose.OPEN_PALM, (0.3, 0.7), (0.7, 0.7), 10) == []


def test_same_direction_allowed_after_cooldown():
    hand = HandSimulator()
    hand.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7))
    assert hand.move(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8) == [GestureEvent(Gesture.SWIPE_LEFT)]
    hand.no_hand(1.0)
    hand.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7))
    assert hand.move(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8) == [GestureEvent(Gesture.SWIPE_LEFT)]


def test_fist_hold_fires_once_until_released():
    hand = HandSimulator()
    assert hand.hold(Pose.FIST, 25) == []  # under 1 s
    assert hand.hold(Pose.FIST, 60) == [GestureEvent(Gesture.FIST_HOLD)]
    hand.hold(Pose.OPEN_PALM, 10)
    assert hand.hold(Pose.FIST, 40) == [GestureEvent(Gesture.FIST_HOLD)]


def test_paused_reports_nothing():
    hand = HandSimulator()
    hand.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7), paused=True)
    assert hand.move(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8, paused=True) == []
    hand.hold(Pose.TWO_FINGERS, 5, paused=True)
    assert hand.move(Pose.TWO_FINGERS, (0.5, 0.8), (0.5, 0.5), 10, paused=True) == []
    assert hand.hold(Pose.FIST, 40, paused=True) == []


def test_scroll_steps_follow_hand():
    hand = HandSimulator()
    hand.hold(Pose.TWO_FINGERS, 5)
    up = hand.move(Pose.TWO_FINGERS, (0.5, 0.8), (0.5, 0.61), 20)
    assert all(event.gesture is Gesture.SCROLL and event.scroll_steps > 0 for event in up)
    assert sum(event.scroll_steps for event in up) == 6  # 0.19 of travel at 0.03 per step
    down = hand.move(Pose.TWO_FINGERS, (0.5, 0.61), (0.5, 0.755), 20)
    assert sum(event.scroll_steps for event in down) == -4


def test_scroll_jitter_does_not_scroll_back():
    hand = HandSimulator()
    hand.hold(Pose.TWO_FINGERS, 5)
    hand.move(Pose.TWO_FINGERS, (0.5, 0.8), (0.5, 0.61), 20)
    # The hand shakes by ±0.02 while drifting slowly up across a whole scroll step,
    # so the shaking crosses a step boundary somewhere.
    events = []
    for rest_y in (0.61, 0.60, 0.59, 0.58):
        for i in range(6):
            events += hand.hold(Pose.TWO_FINGERS, 1, at=(0.5, rest_y + (0.02 if i % 2 else -0.02)))
    assert not any(event.scroll_steps < 0 for event in events)


def test_losing_hand_resets_state():
    hand = HandSimulator()
    hand.hold(Pose.FIST, 20)
    hand.no_hand(0.5)
    assert hand.hold(Pose.FIST, 20) == []  # the hold timer restarted


def test_fist_moving_around_does_not_play_pause():
    # E.g. a hand on the mouse or under the chin, not a deliberate hold.
    hand = HandSimulator()
    assert hand.move(Pose.FIST, (0.3, 0.8), (0.6, 0.8), 60) == []


@pytest.mark.parametrize(
    "palm,swipes",
    [
        ((0.05, 0.5), {Gesture.SWIPE_RIGHT}),
        ((0.95, 0.5), {Gesture.SWIPE_LEFT}),
        ((0.5, 0.05), {Gesture.SWIPE_DOWN}),
        ((0.5, 0.95), {Gesture.SWIPE_UP}),
        ((0.5, 0.5), set()),
    ],
)
def test_swipes_into_view_from_each_edge(palm, swipes):
    assert swipes_into_view(palm) == swipes


def test_hand_coming_into_view_from_the_top_does_not_swipe_down():
    hand = HandSimulator()
    # The wrist at y=0.2 puts the palm center at the top edge of the frame.
    assert hand.move(Pose.OPEN_PALM, (0.5, 0.2), (0.5, 0.65), 12) == []
    hand.hold(Pose.OPEN_PALM, 25, at=(0.5, 0.65))
    assert hand.move(Pose.OPEN_PALM, (0.5, 0.5), (0.5, 0.9), 8) == [GestureEvent(Gesture.SWIPE_DOWN)]
