from handgestures.gestures import Gesture, GestureEvent
from handgestures.hand_poses import Pose
from synthetic_hands import HandSimulator

# Wrist positions for two palms held up side by side. Each hand travels farther than
# swipe_distance, so on its own it would count as a swipe.
LEFT_CLOSE, RIGHT_CLOSE = (0.4, 0.8), (0.6, 0.8)
LEFT_WIDE, RIGHT_WIDE = (0.1, 0.8), (0.9, 0.8)


def test_moving_palms_apart_maximizes():
    hands = HandSimulator()
    hands.hold_two_hands(LEFT_CLOSE, RIGHT_CLOSE, 6)
    events = hands.move_two_hands((LEFT_CLOSE, LEFT_WIDE), (RIGHT_CLOSE, RIGHT_WIDE), 10)
    assert events == [GestureEvent(Gesture.HANDS_APART)]  # and no swipe left/right from either hand


def test_moving_palms_together_restores_down():
    hands = HandSimulator()
    hands.hold_two_hands(LEFT_WIDE, RIGHT_WIDE, 6)
    events = hands.move_two_hands((LEFT_WIDE, LEFT_CLOSE), (RIGHT_WIDE, RIGHT_CLOSE), 10)
    assert events == [GestureEvent(Gesture.HANDS_TOGETHER)]


def test_one_hand_moving_beside_a_still_hand_does_nothing():
    hands = HandSimulator()
    hands.hold_two_hands(LEFT_CLOSE, RIGHT_CLOSE, 6)
    assert hands.move_two_hands((LEFT_CLOSE, LEFT_CLOSE), (RIGHT_CLOSE, (0.95, 0.8)), 10) == []


def test_needs_two_open_palms():
    hands = HandSimulator()
    hands.hold_two_hands(LEFT_CLOSE, RIGHT_CLOSE, 6, pose=Pose.FIST)
    events = hands.move_two_hands((LEFT_CLOSE, LEFT_WIDE), (RIGHT_CLOSE, RIGHT_WIDE), 10, pose=Pose.FIST)
    assert events == []


def test_bringing_hands_back_does_not_restore_down():
    hands = HandSimulator()
    hands.hold_two_hands(LEFT_CLOSE, RIGHT_CLOSE, 6)
    assert hands.move_two_hands((LEFT_CLOSE, LEFT_WIDE), (RIGHT_CLOSE, RIGHT_WIDE), 10) == [
        GestureEvent(Gesture.HANDS_APART)]
    assert hands.move_two_hands((LEFT_WIDE, LEFT_CLOSE), (RIGHT_WIDE, RIGHT_CLOSE), 10) == []


def test_briefly_losing_one_hand_does_not_cancel_the_gesture():
    hands = HandSimulator()
    hands.hold_two_hands(LEFT_CLOSE, RIGHT_CLOSE, 6)
    events = hands.move_two_hands((LEFT_CLOSE, LEFT_WIDE), (RIGHT_CLOSE, RIGHT_WIDE), 10, one_hand_frames={4})
    assert events == [GestureEvent(Gesture.HANDS_APART)]


def test_lowering_a_hand_after_two_hand_gesture_does_not_swipe():
    hands = HandSimulator()
    hands.hold_two_hands(LEFT_CLOSE, RIGHT_CLOSE, 6)
    hands.move_two_hands((LEFT_CLOSE, LEFT_WIDE), (RIGHT_CLOSE, RIGHT_WIDE), 10)
    # The left hand drops out of view, and the right one is lowered quickly.
    assert hands.move(Pose.OPEN_PALM, (0.8, 0.5), (0.8, 0.95), 8) == []


def test_one_hand_gestures_work_again_after_the_holdoff():
    hands = HandSimulator()
    hands.hold_two_hands(LEFT_CLOSE, RIGHT_CLOSE, 6)
    hands.move_two_hands((LEFT_CLOSE, LEFT_WIDE), (RIGHT_CLOSE, RIGHT_WIDE), 10)
    hands.no_hand(1.0)
    hands.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7))
    assert hands.move(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8) == [GestureEvent(Gesture.SWIPE_LEFT)]


def test_pose_label_shows_both_hands():
    hands = HandSimulator()
    hands.hold_two_hands(LEFT_CLOSE, RIGHT_CLOSE, 10)
    assert hands.detector.pose_label == "open palm + open palm"


def test_second_hand_seen_for_a_frame_does_not_interrupt_a_swipe():
    # MediaPipe sometimes reports the same hand twice for a frame, mostly during fast moves.
    hands = HandSimulator()
    hands.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7))
    events = hands.move(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8, phantom_frames={2})
    assert events == [GestureEvent(Gesture.SWIPE_LEFT)]


def test_second_hand_seen_for_a_frame_does_not_pause_one_hand_gestures():
    hands = HandSimulator()
    hands.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7))
    hands.move(Pose.OPEN_PALM, (0.7, 0.7), (0.7, 0.7), 2, phantom_frames={0})
    assert hands.move(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8) == [GestureEvent(Gesture.SWIPE_LEFT)]
