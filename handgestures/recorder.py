"""Records hand movements, so gestures can be tuned against how hands really move.

A recording is a JSON Lines file: a header line with the settings, then one line per
camera frame with the time, each hand's 21 points and the gestures detected. It holds
no camera image.
"""
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .config import Config
from .gesture_detector import GestureDetector
from .gestures import GestureEvent
from .hand_landmarks import Landmarks
from .paths import RECORDINGS_DIR

FORMAT_NAME = "handgestures-recording"
FORMAT_VERSION = 1
POINT_DECIMALS = 4  # 0.0001 of the frame is far finer than tracking noise


def new_recording_path(kind: str) -> Path:
    """E.g. recordings/guided-20260928-201530.jsonl"""
    return RECORDINGS_DIR / f"{kind}-{datetime.now():%Y%m%d-%H%M%S}.jsonl"


class Recorder:
    """Use as a context manager, or call close(), so the file is complete."""

    def __init__(self, path: Path, config: Config):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        # Line buffered, so a crash or forced stop loses at most one frame.
        self._file = path.open("w", encoding="utf-8", buffering=1)
        self._first_frame_time: float | None = None
        self._write({
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "started": datetime.now().isoformat(timespec="seconds"),
            "config": asdict(config),
        })

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def add_frame(self, now: float, hands: list[Landmarks], events: list[GestureEvent], label: str | None = None):
        """Record one frame seen at `now` (time.monotonic() seconds). `label` names what the user was asked to do."""
        if self._file.closed:
            return  # the app is shutting down
        if self._first_frame_time is None:
            self._first_frame_time = now
        frame = {
            "t": round(now - self._first_frame_time, 4),
            "hands": [[[round(value, POINT_DECIMALS) for value in point] for point in hand] for hand in hands],
            "events": [str(event) for event in events],
        }
        if label:
            frame["label"] = label
        self._write(frame)

    def close(self):
        self._file.close()

    def _write(self, record: dict):
        self._file.write(json.dumps(record, separators=(",", ":")) + "\n")


@dataclass(frozen=True)
class RecordedFrame:
    time: float  # seconds since the first frame
    hands: list[Landmarks]
    events: list[str]  # as detected live, e.g. ["swipe left"]
    label: str | None


def read_recording(path: Path) -> tuple[dict, list[RecordedFrame]]:
    """Return the recording's header (with the settings it was made with) and its frames."""
    with Path(path).open(encoding="utf-8") as file:
        header = json.loads(file.readline())
        if header.get("format") != FORMAT_NAME:
            raise ValueError(f"{path} is not a HandGestures recording")
        frames = []
        for line in file:
            if not line.strip():
                continue
            frame = json.loads(line)
            frames.append(RecordedFrame(
                time=frame["t"],
                hands=[[tuple(point) for point in hand] for hand in frame["hands"]],
                events=frame["events"],
                label=frame.get("label"),
            ))
    return header, frames


def replay(frames: list[RecordedFrame], config: Config) -> list[list[GestureEvent]]:
    """Run recorded frames through a fresh GestureDetector; return the events detected in each frame."""
    detector = GestureDetector(config)
    return [detector.update(frame.hands, frame.time) for frame in frames]
