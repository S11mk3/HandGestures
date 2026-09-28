"""Replays a recording through the gesture detector and reports what it detects.

    python -m tools.replay_recording recordings/guided-20260928-201530.jsonl
    python -m tools.replay_recording <file> --set swipe_distance=0.15 --set two_hand_window_s=0.6

Uses the current settings (config.json), changed by any --set, so a new setting can be
checked against earlier recordings before using it.
"""
import argparse
from collections import Counter
from dataclasses import asdict, fields, replace
from itertools import groupby
from pathlib import Path

from handgestures.config import Config, load_config
from handgestures.gestures import GestureEvent
from handgestures.recorder import RecordedFrame, read_recording, replay
from tools.guided_steps import GET_READY_LABEL, STEPS

EXPECTED_BY_LABEL = {step.label: step for step in STEPS}


def parse_setting(text: str) -> tuple[str, int | float]:
    """ "swipe_distance=0.15" -> ("swipe_distance", 0.15), typed like the setting."""
    name, _, value = text.partition("=")
    setting_types = {field.name: field.type for field in fields(Config)}
    if name not in setting_types:
        raise argparse.ArgumentTypeError(f"unknown setting {name!r}; see handgestures/config.py")
    try:
        return name, setting_types[name](value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{name} needs a {setting_types[name].__name__}, got {value!r}")


def format_time(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def count_gestures(events: list[GestureEvent]) -> Counter:
    return Counter(event.gesture.value for event in events)


def describe_counts(counts: Counter) -> str:
    return ", ".join(f"{gesture} x{count}" for gesture, count in counts.items()) or "nothing"


def hands_seen(frames: list[RecordedFrame]) -> str:
    """Share of frames with 0, 1 and 2 hands, e.g. "2% / 95% / 3%": how well tracking kept up."""
    counts = Counter(min(len(frame.hands), 2) for frame in frames)
    return " / ".join(f"{counts[hand_count] / len(frames):.0%}" for hand_count in (0, 1, 2))


def report_steps(frames: list[RecordedFrame], events_per_frame: list[list[GestureEvent]]):
    print(f"{'step':16s}{'expected':24s}{'detected':34s}hands seen 0 / 1 / 2")
    indexed = list(zip(frames, events_per_frame))
    for label, group in groupby(indexed, key=lambda pair: pair[0].label):
        group = list(group)
        step_frames = [frame for frame, _ in group]
        events = [event for _, frame_events in group for event in frame_events]
        counts = count_gestures(events)
        step = EXPECTED_BY_LABEL.get(label)
        if label == GET_READY_LABEL:
            if events:  # only worth showing when something fired between steps
                print(f"{'  (get ready)':16s}{'nothing':24s}{describe_counts(counts):34s}  <-- check")
            continue
        if step is None:
            print(f"{label or '(no label)':16s}{'?':24s}{describe_counts(counts)}")
            continue

        expected_name = step.expected_gesture.value if step.expected_gesture else None
        if expected_name is None:
            expected = "nothing"
        elif step.expected_count is None:
            expected = f"{expected_name} (any)"
        else:
            expected = f"{expected_name} x{step.expected_count}"
        unexpected = {gesture: count for gesture, count in counts.items() if gesture != expected_name}
        count_is_right = step.expected_count is None or counts[expected_name] == step.expected_count
        found_expected = expected_name is None or counts[expected_name] > 0
        flag = "" if count_is_right and found_expected and not unexpected else "  <-- check"
        print(f"{label:16s}{expected:24s}{describe_counts(counts):34s}{hands_seen(step_frames)}{flag}")
        for frame, frame_events in group:
            for event in frame_events:
                if event.gesture.value != expected_name:
                    print(f"{'':16s}  unexpected {event} at {format_time(frame.time)}")


def report_timeline(frames: list[RecordedFrame], events_per_frame: list[list[GestureEvent]]):
    print("time     gesture")
    for frame, events in zip(frames, events_per_frame):
        for event in events:
            print(f"{format_time(frame.time):9s}{event}")
    if not any(events_per_frame):
        print("(no gestures)")
    print(f"\nhands seen 0 / 1 / 2: {hands_seen(frames)}")


def main():
    parser = argparse.ArgumentParser(description="Replay a HandGestures recording through the gesture detector.")
    parser.add_argument("recording", type=Path)
    parser.add_argument("--set", type=parse_setting, action="append", default=[], metavar="NAME=VALUE",
                        help="try a different setting, e.g. --set swipe_distance=0.15")
    args = parser.parse_args()

    config = replace(load_config(), **dict(args.set))
    header, frames = read_recording(args.recording)
    if not frames:
        print("The recording has no frames.")
        return
    events_per_frame = replay(frames, config)

    duration = frames[-1].time
    print(f"{args.recording.name}: {len(frames)} frames over {format_time(duration)} "
          f"({len(frames) / max(duration, 1e-9):.1f} fps)")
    recorded_settings = header["config"]
    changed = {name: value for name, value in asdict(config).items() if recorded_settings.get(name) != value}
    if changed:
        print("Settings different from the recording's: "
              + ", ".join(f"{name}={value} (was {recorded_settings.get(name)})" for name, value in changed.items()))
    live_count = sum(len(frame.events) for frame in frames)
    replay_count = sum(len(events) for events in events_per_frame)
    print(f"Gestures detected live: {live_count}, in this replay: {replay_count}\n")

    if any(frame.label for frame in frames):
        report_steps(frames, events_per_frame)
    else:
        report_timeline(frames, events_per_frame)


if __name__ == "__main__":
    main()
