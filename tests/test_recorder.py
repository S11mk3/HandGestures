import json

import pytest

from handgestures.config import Config
from handgestures.gestures import Gesture, GestureEvent
from handgestures.hand_poses import Pose
from handgestures.recorder import Recorder, read_recording, replay
from synthetic_hands import HandSimulator, make_hand


def test_recording_reads_back_what_was_written(tmp_path):
    path = tmp_path / "recording.jsonl"
    hand = make_hand(Pose.OPEN_PALM, 0.5, 0.8)
    with Recorder(path, Config()) as recorder:
        recorder.add_frame(100.0, [], [])
        recorder.add_frame(100.5, [hand], [GestureEvent(Gesture.SCROLL, 2)], label="scroll")

    header, frames = read_recording(path)
    assert header["config"]["swipe_distance"] == Config().swipe_distance
    assert [frame.time for frame in frames] == [0.0, 0.5]  # seconds since the first frame
    assert frames[0].hands == [] and frames[0].label is None
    assert frames[1].hands[0] == pytest.approx([tuple(round(v, 4) for v in point) for point in hand])
    assert frames[1].events == ["scroll +2"]
    assert frames[1].label == "scroll"


def test_replay_detects_the_same_gestures_as_live(tmp_path):
    path = tmp_path / "recording.jsonl"
    hands = HandSimulator()
    original_update = hands.detector.update
    with Recorder(path, Config()) as recorder:
        def update_and_record(frame_hands, now, paused=False):
            events = original_update(frame_hands, now, paused)
            recorder.add_frame(now, frame_hands, events)
            return events
        hands.detector.update = update_and_record
        hands.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7))
        live_events = hands.move(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8)
        hands.hold_two_hands((0.35, 0.8), (0.65, 0.8), 40)
        live_events += hands.move_two_hands(((0.35, 0.8), (0.2, 0.8)), ((0.65, 0.8), (0.8, 0.8)), 10)

    assert live_events == [GestureEvent(Gesture.SWIPE_LEFT), GestureEvent(Gesture.HANDS_APART)]
    _, frames = read_recording(path)
    replayed = [event for frame_events in replay(frames, Config()) for event in frame_events]
    assert replayed == live_events


def test_rejects_files_that_are_not_recordings(tmp_path):
    path = tmp_path / "other.jsonl"
    path.write_text(json.dumps({"hello": "world"}) + "\n")
    with pytest.raises(ValueError):
        read_recording(path)
