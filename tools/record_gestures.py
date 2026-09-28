"""Guided recording: prompts each gesture in turn and records your hand movements.

    python -m tools.record_gestures

Takes about 3 minutes. Nothing happens on your PC while it runs. Only hand positions
are saved (no camera image), to recordings/guided-<date>-<time>.jsonl.
Close the preview window or press Ctrl+C to stop early; what was recorded so far is kept.
"""
import logging
import sys
import time
from collections import Counter

from handgestures.camera import Camera, CameraUnavailableError
from handgestures.config import Config, load_config
from handgestures.gesture_detector import GestureDetector
from handgestures.gestures import GestureEvent
from handgestures.hand_tracker import HandTracker
from handgestures.preview_window import Overlay, PreviewWindow
from handgestures.recorder import Recorder, new_recording_path
from tools.guided_steps import GET_READY_LABEL, GET_READY_S, STEPS

PREVIEW_WIDTH = 640  # wider than usual so the instructions fit
LAST_EVENT_DISPLAY_S = 2.0
FIRST_FRAME_TIMEOUT_S = 5.0


class SessionStopped(Exception):
    """The user closed the preview window."""


class GuidedSession:
    def __init__(self, camera: Camera, tracker: HandTracker, recorder: Recorder, config: Config):
        self._camera = camera
        self._tracker = tracker
        self._recorder = recorder
        self._detector = GestureDetector(config)
        self._preview = PreviewWindow(PREVIEW_WIDTH)
        self._last_event, self._last_event_time = "", float("-inf")

    def run_phase(self, label: str, prompt: str, seconds: float) -> list[GestureEvent]:
        """Record for `seconds` with `prompt` on screen. Return the gestures detected."""
        detected = []
        end_time = time.monotonic() + seconds
        while (remaining_s := end_time - time.monotonic()) > 0:
            frame = self._camera.latest_frame()
            if frame is None:
                continue
            hands = self._tracker.find_hands(frame.image)
            now = time.monotonic()
            events = self._detector.update(hands, now)
            self._recorder.add_frame(now, hands, events, label)
            for event in events:
                detected.append(event)
                self._last_event, self._last_event_time = str(event), now

            last_event = self._last_event if now - self._last_event_time < LAST_EVENT_DISPLAY_S else ""
            overlay = Overlay(hands, self._detector.pose_label, speed="", last_action=last_event,
                              paused=False, prompt=f"{prompt}  {remaining_s:.0f}s")
            if not self._preview.show(frame.image, overlay):
                raise SessionStopped
        return detected

    def close(self):
        self._preview.close()


def summarize(events: list[GestureEvent]) -> str:
    """E.g. "swipe left x4, swipe down x1"."""
    counts = Counter(event.gesture.value for event in events)
    return ", ".join(f"{gesture} x{count}" for gesture, count in counts.items()) or "nothing"


def main():
    logging.basicConfig(level=logging.WARNING)
    config = load_config()
    path = new_recording_path("guided")
    try:
        camera = Camera(config.camera_index, config.frame_width, config.frame_height)
    except CameraUnavailableError as error:
        sys.exit(f"{error}. If HandGestures is running, quit it from the tray icon first.")

    print(f"Recording to {path}")
    print("Follow the instructions in the preview window. Close it or press Ctrl+C to stop early.\n")
    try:
        with camera, HandTracker(config) as tracker, Recorder(path, config) as recorder:
            if camera.latest_frame(timeout_s=FIRST_FRAME_TIMEOUT_S) is None:
                sys.exit("No picture from the camera. If HandGestures is running, quit it from the tray icon first.")
            session = GuidedSession(camera, tracker, recorder, config)
            try:
                for number, step in enumerate(STEPS, start=1):
                    session.run_phase(GET_READY_LABEL, f"Next: {step.prompt}", GET_READY_S)
                    print(f"{number}/{len(STEPS)} {step.label:15s}", end="", flush=True)
                    print(f"detected: {summarize(session.run_phase(step.label, step.prompt, step.seconds))}")
            finally:
                session.close()
    except (SessionStopped, KeyboardInterrupt):
        print("\nStopped early; what was recorded so far is saved.")

    print(f"\nSaved {path}")
    print(f"Replay it with: python -m tools.replay_recording {path}")


if __name__ == "__main__":
    main()
