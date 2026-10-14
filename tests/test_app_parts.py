"""Tests for the smaller parts: bindings, cooldown, duplicate hands, the battery saver, input structures."""
import ctypes

from hard2gesture.actions import ActionRunner
from hard2gesture.bindings import ACTIONS, BINDABLE_GESTURES, DEFAULT_GESTURE_ACTIONS, describe
from hard2gesture.gestures import Cooldown, Gesture, GestureEvent
from hard2gesture.hand_poses import Pose
from hard2gesture.hand_tracker import remove_duplicate_hands
from hard2gesture.tracking_loop import IDLE_AFTER_S, IDLE_TRACKING_FPS, TrackingRate
from hard2gesture.windows_input import INPUT

from synthetic_hands import make_hand


def test_every_action_has_an_implementation():
    ActionRunner(dry_run=True)  # asserts that none is missing


def test_default_bindings_are_valid():
    assert all(action in ACTIONS for action in DEFAULT_GESTURE_ACTIONS.values())
    assert len(BINDABLE_GESTURES) == len(DEFAULT_GESTURE_ACTIONS)


def test_describe():
    actions = {**DEFAULT_GESTURE_ACTIONS, "fist_hold": "mute"}
    assert describe(GestureEvent(Gesture.FIST_HOLD), actions) == "Mute"
    assert describe(GestureEvent(Gesture.SCROLL, -2), actions) == "Scroll -2"
    assert describe(GestureEvent(Gesture.PINCH), actions) == "Click"


def test_cooldown_blocks_the_return_stroke_longer():
    cooldown = Cooldown(cooldown_s=0.8, opposite_cooldown_s=1.6)
    cooldown.record(Gesture.SWIPE_LEFT, 0.0)
    assert not cooldown.allows(Gesture.SWIPE_UP, 0.5)
    assert cooldown.allows(Gesture.SWIPE_UP, 1.0)
    assert not cooldown.allows(Gesture.SWIPE_RIGHT, 1.0)
    assert cooldown.allows(Gesture.SWIPE_RIGHT, 1.7)


def test_one_hand_reported_twice_is_one_hand():
    hand = make_hand(Pose.OPEN_PALM, 0.5, 0.8)
    copy = make_hand(Pose.OPEN_PALM, 0.51, 0.81)
    assert len(remove_duplicate_hands([hand, copy])) == 1
    other_hand = make_hand(Pose.OPEN_PALM, 0.8, 0.8)
    assert len(remove_duplicate_hands([hand, other_hand])) == 2


def test_battery_saver_tracks_less_often_with_no_hand_in_view():
    rate = TrackingRate()
    frames = [i / 30 for i in range(30)]
    hand_just_seen = sum(rate.should_track(now, now, True, False, False) for now in frames)
    assert hand_just_seen == 30
    long_ago = -IDLE_AFTER_S - 1
    idle = sum(rate.should_track(1 + now, long_ago, True, False, False) for now in frames)
    assert IDLE_TRACKING_FPS - 1 <= idle <= IDLE_TRACKING_FPS  # every 4th frame of 30: 7 or 8 a second
    switched_off = sum(rate.should_track(2 + now, long_ago, False, False, False) for now in frames)
    assert switched_off == 30


def test_input_structure_matches_windows():
    assert ctypes.sizeof(INPUT) == 40  # what SendInput expects on 64-bit Windows
