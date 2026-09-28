"""The background thread that reads the camera, detects gestures and performs their actions."""
import logging
import threading
import time

from .actions import Actions, describe, perform
from .app_state import AppState
from .camera import Camera, CameraUnavailableError
from .config import Config
from .gesture_detector import GestureDetector
from .gestures import GestureEvent
from .hand_tracker import HandTracker
from .paths import LOG_PATH
from .preview_window import Overlay, PreviewWindow
from .recorder import Recorder

log = logging.getLogger(__name__)

LAST_ACTION_DISPLAY_S = 2.0  # how long the preview shows the last action


class FrameStats:
    """Moving averages of the frame rate and of frame age: the time from capture to gesture decision."""

    SMOOTHING = 0.1  # weight of the newest frame

    def __init__(self):
        self.fps = 0.0
        self.frame_age_ms = 0.0
        self._previous_frame_time: float | None = None

    def add_frame(self, capture_time: float, decision_time: float):
        if self._previous_frame_time is not None:
            interval = decision_time - self._previous_frame_time
            self.fps = self._average(self.fps, 1 / interval if interval > 0 else self.fps)
        self.frame_age_ms = self._average(self.frame_age_ms, (decision_time - capture_time) * 1000)
        self._previous_frame_time = decision_time

    def _average(self, current: float, newest: float) -> float:
        return newest if current == 0 else current + self.SMOOTHING * (newest - current)

    def __str__(self):
        return f"{self.fps:.0f} fps, {self.frame_age_ms:.0f} ms"


class CameraLoop:
    def __init__(self, state: AppState, config: Config, actions: Actions, recorder: Recorder | None = None):
        self._state = state
        self._config = config
        self._actions = actions
        self._recorder = recorder
        self._stop_requested = threading.Event()
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self, timeout_s: float = 3):
        self._stop_requested.set()
        self._thread.join(timeout_s)

    def _run(self):
        config = self._config
        preview = PreviewWindow(config.preview_width)
        try:
            with (
                Camera(config.camera_index, config.frame_width, config.frame_height) as camera,
                HandTracker(config) as tracker,
            ):
                self._process_frames(camera, tracker, preview)
        except CameraUnavailableError as error:
            log.error(error)
            self._state.set_status(str(error))
        except Exception:
            log.exception("Camera loop crashed")
            self._state.set_status(f"Error - see {LOG_PATH.name}")
        finally:
            preview.close()

    def _process_frames(self, camera: Camera, tracker: HandTracker, preview: PreviewWindow):
        detector = GestureDetector(self._config)
        stats = FrameStats()
        self._state.set_status("Running")
        log.info("Tracking started on camera %d", self._config.camera_index)
        last_action, last_action_time = "", float("-inf")

        while not self._stop_requested.is_set():
            frame = camera.latest_frame()
            if frame is None:
                continue  # no new frame yet; check for stop and wait again
            hands = tracker.find_hands(frame.image)
            now = time.monotonic()

            events = detector.update(hands, now, paused=self._state.paused)
            for event in events:
                last_action, last_action_time = describe(event), now
                log.info("Gesture: %s -> %s", event.gesture.value, last_action)
                self._perform(event)
            if self._recorder:
                self._recorder.add_frame(now, hands, events)
            if now - last_action_time > LAST_ACTION_DISPLAY_S:
                last_action = ""
            stats.add_frame(frame.capture_time, now)

            if not self._state.show_preview:
                preview.close()
                continue
            overlay = Overlay(hands, detector.pose_label, str(stats), last_action, self._state.paused)
            if not preview.show(frame.image, overlay):
                self._state.show_preview = False  # the user closed the window
                self._state.notify_changed()

    def _perform(self, event: GestureEvent):
        try:
            perform(self._actions, event)
        except Exception:
            log.exception("Action for %s failed", event.gesture.value)
