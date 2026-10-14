"""The background thread that reads the camera, finds hands, recognizes gestures and acts on them."""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

import numpy as np

from .actions import ActionRunner
from .app_state import AppState
from .bindings import action_for, describe
from .calibration import Calibration, CalibrationStatus, load_profile, save_profile
from .camera import Camera, CameraUnavailableError
from .config import Config, ConfigStore
from .gesture_detector import GestureDetector
from .gestures import Gesture, GestureEvent
from .hand_landmarks import Hand
from .hand_poses import HandScale, palm_length_in_frame
from .hand_tracker import HandTracker
from .image_tuning import VERDICT_ADVICE, ImageTuner, LightingVerdict
from .paths import LOG_PATH
from .pointer_driver import Cursor, PointerController

log = logging.getLogger(__name__)

LAST_ACTION_DISPLAY_S = 2.0  # how long the preview shows the last action
CAMERA_STALL_S = 2.0  # no frames for this long: the camera is reopened
RECONNECT_DELAYS_S = (1, 2, 5)  # between attempts to open the camera; the last one repeats
BLACK_PICTURE_WARNING_S = 3.0
FRAME_ERROR_LOG_EVERY = 300
# Battery saver: with no hand seen for IDLE_AFTER_S, look for one IDLE_TRACKING_FPS times a second.
# Searching an empty frame is the most expensive case: MediaPipe runs its palm detector on every one.
IDLE_AFTER_S = 5.0
IDLE_TRACKING_FPS = 8
PAUSED_TRACKING_FPS = 2  # while paused with no camera image on screen


class StatusKind(Enum):
    STARTING = "starting"
    CALIBRATING = "calibrating"
    RUNNING = "running"
    PROBLEM = "problem"


@dataclass(frozen=True)
class Status:
    kind: StatusKind
    message: str


@dataclass(frozen=True)
class FrameView:
    """One camera frame and what was recognized in it, for the windows that show the camera image."""
    image: np.ndarray  # BGR, as hand tracking saw it (brightened if the room is dim)
    hands: list[Hand]
    pose_label: str  # e.g. "fist" or "open palm + open palm"
    last_action: str  # empty when there's none to show
    paused: bool
    details: str  # tracking details, e.g. "30 fps, 45 ms · hand x1.0"


class TrackingListener(Protocol):
    """Receives the camera thread's news. Called on the camera thread."""
    def on_status(self, status: Status) -> None: ...
    def on_frame(self, view: FrameView) -> None: ...
    def on_gesture(self, event: GestureEvent, description: str) -> None: ...
    def on_calibration(self, status: CalibrationStatus) -> None: ...


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


class TrackingRate:
    """Decides which frames to look for hands in: every one, unless the battery saver says otherwise."""

    def __init__(self):
        self._last_tracked = float("-inf")
        self.saving = False  # tracking less often than every frame

    def should_track(self, now: float, last_hand_time: float, battery_saver: bool,
                     paused: bool, frames_wanted: bool) -> bool:
        interval = 0.0
        if battery_saver:
            if paused and not frames_wanted:
                interval = 1 / PAUSED_TRACKING_FPS
            elif now - last_hand_time > IDLE_AFTER_S:
                interval = 1 / IDLE_TRACKING_FPS
        self.saving = interval > 0
        if now - self._last_tracked >= interval:
            self._last_tracked = now
            return True
        return False


class TrackingLoop:
    """Runs the camera thread. Settings changes in the ConfigStore apply from the next frame."""

    def __init__(self, store: ConfigStore, state: AppState, listener: TrackingListener,
                 actions: ActionRunner, cursor: Cursor | None, calibrate_first: bool):
        self._store = store
        self._state = state
        self._listener = listener
        self._actions = actions
        self._cursor = cursor  # None: dry run, the pointer doesn't move
        self._calibrate_first = calibrate_first
        self._stop_requested = threading.Event()
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._status: Status | None = None

    def start(self):
        self._thread.start()

    def stop(self, timeout_s: float = 3):
        self._stop_requested.set()
        self._thread.join(timeout_s)

    # Setup and teardown

    def _run(self):
        self._camera: Camera | None = None
        self._tracker: HandTracker | None = None
        self._pointer = PointerController(self._store.config, self._cursor)
        try:
            self._set_status(StatusKind.STARTING, "Starting…")
            self._setup()
            self._process_frames()
        except Exception:
            log.exception("Camera loop crashed")
            self._set_status(StatusKind.PROBLEM, f"Something went wrong. The details are in {LOG_PATH.name}.")
        finally:
            self._pointer.close()
            if self._camera:
                self._camera.close()
            if self._tracker:
                self._tracker.close()

    def _setup(self):
        self._config: Config = self._store.config
        self._config_revision = self._store.revision
        self._profile = load_profile()
        self._tuner = ImageTuner()
        self._hand_scale = HandScale(self._profile.palm_length)
        self._detector = GestureDetector(self._config, self._profile.pointer_cutoff_hz)
        self._calibration: Calibration | None = None
        self._rate = TrackingRate()
        self._stats = FrameStats()
        self._last_hands: list[Hand] = []
        self._last_hand_time = float("-inf")
        self._last_frame_time = float("-inf")
        self._last_action, self._last_action_time = "", float("-inf")
        self._black_since: float | None = None
        self._awaiting_first_frame = False
        self._frame_errors = 0
        self._reconnect_attempt = 0
        self._next_reconnect_time = 0.0

        # Opening a camera takes seconds, and so does loading the hand model the first time: do both at once.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="camera-open") as pool:
            camera = pool.submit(self._open_camera)
            self._tracker = self._create_tracker()
            self._camera = camera.result()
        if self._camera is not None:
            self._on_camera_opened()
        if self._calibrate_first:
            self._start_calibration()

    def _open_camera(self) -> Camera | None:
        config = self._config
        try:
            return Camera(config.camera_index, config.frame_width, config.frame_height)
        except CameraUnavailableError as error:
            log.warning("%s", error)
            return None

    def _create_tracker(self) -> HandTracker:
        detection_confidence = self._config.min_detection_confidence
        if self._profile.detection_confidence is not None:
            detection_confidence = min(detection_confidence, self._profile.detection_confidence)
        return HandTracker(detection_confidence, self._config.min_tracking_confidence)

    # The loop

    def _process_frames(self):
        while not self._stop_requested.is_set():
            self._apply_config_changes()
            if self._state.calibration_requested.is_set():
                self._state.calibration_requested.clear()
                self._start_calibration()
            if self._camera is None:
                self._try_reconnecting()
                continue
            frame = self._camera.latest_frame(timeout_s=0.25)
            now = time.monotonic()
            if frame is None:
                if now - self._last_frame_time > CAMERA_STALL_S:
                    log.warning("No frames for %.0f s; reopening the camera", CAMERA_STALL_S)
                    self._set_status(StatusKind.PROBLEM, "The camera stopped sending pictures. Reconnecting…")
                    self._close_camera()
                continue
            if self._awaiting_first_frame:
                self._awaiting_first_frame = False
                self._reconnect_attempt = 0
                self._set_status(*self._normal_status())
            self._last_frame_time = now
            try:
                self._process(frame.image, frame.capture_time, now)
            except Exception:
                # One bad frame mustn't end tracking for the session; log the first and then every 300th.
                self._frame_errors += 1
                if self._frame_errors % FRAME_ERROR_LOG_EVERY == 1:
                    log.exception("Processing a frame failed (%d times so far)", self._frame_errors)

    def _try_reconnecting(self):
        now = time.monotonic()
        if now >= self._next_reconnect_time:
            self._camera = self._open_camera()
            if self._camera is not None:
                self._on_camera_opened()
                return
            delay = RECONNECT_DELAYS_S[min(self._reconnect_attempt, len(RECONNECT_DELAYS_S) - 1)]
            self._reconnect_attempt += 1
            self._next_reconnect_time = now + delay
            self._set_status(StatusKind.PROBLEM,
                             f"Can't use camera {self._config.camera_index + 1}. It may be unplugged, or in use by "
                             "another app such as a video call. Retrying…")
        self._stop_requested.wait(0.2)

    def _on_camera_opened(self):
        self._awaiting_first_frame = True
        self._last_frame_time = time.monotonic()  # it has CAMERA_STALL_S to deliver its first frame

    def _close_camera(self):
        if self._camera:
            self._camera.close()
        self._camera = None
        self._next_reconnect_time = time.monotonic() + RECONNECT_DELAYS_S[0]

    def _process(self, raw_image: np.ndarray, capture_time: float, now: float):
        state, config = self._state, self._config
        self._tuner.observe(raw_image, now)
        image = self._tuner.apply(raw_image)
        self._check_for_black_picture(now)

        calibrating = self._calibration is not None
        hands = None
        if calibrating or self._rate.should_track(
                now, self._last_hand_time, config.battery_saver, state.paused, state.frames_wanted):
            # A pointing hand can't be half of a two-hand gesture (those need open palms), and
            # searching for a second hand every few frames would make the pointer stutter.
            look_for_second_hand = not calibrating and self._detector.pointer_position is None
            hands = self._tracker.find_hands(image, capture_time, look_for_second_hand)
            self._last_hands = hands
            if hands:
                self._last_hand_time = now
                self._hand_scale.update(max(hands, key=palm_length_in_frame), now)
            self._stats.add_frame(capture_time, time.monotonic())

        if calibrating:
            self._calibrate(raw_image, hands or [], now)
        elif hands is not None:
            self._recognize(hands, now)

        if now - self._last_action_time > LAST_ACTION_DISPLAY_S:
            self._last_action = ""
        if state.frames_wanted:
            self._listener.on_frame(FrameView(
                image, self._last_hands, self._detector.pose_label, self._last_action, state.paused, self._details()))

    def _recognize(self, hands: list[Hand], now: float):
        state = self._state
        scale = self._hand_scale.factor
        events = self._detector.update(hands, now, scale, paused=state.paused)
        moves_pointer = not (state.paused or state.practice_mode)
        # Before any click, so it lands where the pointer is held for it.
        self._pointer.update(self._detector.pointer_position if moves_pointer else None,
                             self._detector.pointer_segment, scale, now)
        for event in events:
            description = describe(event, self._config.gesture_actions)
            self._last_action, self._last_action_time = description, now
            log.info("Gesture: %s -> %s%s", event.gesture.label, description,
                     " (practice, not performed)" if state.practice_mode else "")
            self._listener.on_gesture(event, description)
            if not state.practice_mode:
                self._perform(event)

    def _perform(self, event: GestureEvent):
        try:
            if event.gesture is Gesture.PINCH:
                self._pointer.click(event.aim_time)
            elif event.gesture is Gesture.DOUBLE_PINCH:
                self._pointer.double_click()
            elif event.gesture is Gesture.SCROLL:
                self._actions.scroll(event.scroll_steps, self._config.scroll_amount)
            else:
                self._actions.run(action_for(event.gesture, self._config.gesture_actions))
        except Exception:
            log.exception("Action for %s failed", event.gesture.label)

    # Calibration

    def _start_calibration(self):
        self._pointer.release()
        self._state.calibration_skip_requested.clear()
        detection_confidence = self._tracker.detection_confidence if self._tracker else 0.6
        self._calibration = Calibration(self._tuner, self._profile, detection_confidence)
        self._set_status(*self._normal_status())

    def _calibrate(self, raw_image: np.ndarray, hands: list[Hand], now: float):
        if self._state.calibration_skip_requested.is_set():
            self._state.calibration_skip_requested.clear()
            self._calibration.skip(now)
        status = self._calibration.update(raw_image, hands, now)
        self._listener.on_calibration(status)
        if not self._calibration.finished:
            return
        if status.hand_measured:
            self._profile = self._calibration.profile
            save_profile(self._profile)
            self._hand_scale = HandScale(self._profile.palm_length)
            self._detector = GestureDetector(self._config, self._profile.pointer_cutoff_hz)
            self._rebuild_tracker_if_needed()
        self._calibration = None
        self._set_status(*self._normal_status())

    # Settings

    def _apply_config_changes(self):
        if self._store.revision == self._config_revision:
            return
        old, new = self._config, self._store.config
        self._config, self._config_revision = new, self._store.revision
        if (old.camera_index, old.frame_width, old.frame_height) != (new.camera_index, new.frame_width,
                                                                      new.frame_height):
            log.info("Camera settings changed; reopening the camera")
            self._close_camera()
            self._next_reconnect_time = 0.0
            self._reconnect_attempt = 0
        self._rebuild_tracker_if_needed()
        self._detector = GestureDetector(new, self._profile.pointer_cutoff_hz)
        self._pointer.configure(new)

    def _rebuild_tracker_if_needed(self):
        tracker = self._tracker
        wanted = self._config.min_detection_confidence
        if self._profile.detection_confidence is not None:
            wanted = min(wanted, self._profile.detection_confidence)
        if tracker and (tracker.detection_confidence, tracker.tracking_confidence) != (
                wanted, self._config.min_tracking_confidence):
            tracker.close()
            self._tracker = self._create_tracker()

    # Status

    def _normal_status(self) -> tuple[StatusKind, str]:
        if self._calibration is not None:
            return StatusKind.CALIBRATING, "Calibrating…"
        if self._cursor is None:
            return StatusKind.RUNNING, "Running (dry run: gestures are only logged)"
        return StatusKind.RUNNING, "Running"

    def _set_status(self, kind: StatusKind, message: str):
        status = Status(kind, message)
        if status != self._status:
            self._status = status
            log.info("Status: %s", message)
            self._listener.on_status(status)

    def _check_for_black_picture(self, now: float):
        lighting = self._tuner.lighting
        if lighting is not None and lighting.is_black:
            if self._black_since is None:
                self._black_since = now
            elif now - self._black_since > BLACK_PICTURE_WARNING_S:
                self._set_status(StatusKind.PROBLEM, VERDICT_ADVICE[LightingVerdict.NO_PICTURE])
            return
        if self._black_since is not None and self._status.kind is StatusKind.PROBLEM:
            self._set_status(*self._normal_status())
        self._black_since = None

    def _details(self) -> str:
        parts = [str(self._stats), f"hand x{self._hand_scale.factor:.2f}"]
        if self._tuner.gamma != 1.0 or self._tuner.equalize:
            parts.append(f"brightened (gamma {self._tuner.gamma:.2f}{', contrast' if self._tuner.equalize else ''})")
        pinch = self._detector.pinch_ratio
        if pinch is not None:
            parts.append(f"pinch {pinch:.2f}")
        if self._rate.saving:
            parts.append("battery saver")
        return " · ".join(parts)
