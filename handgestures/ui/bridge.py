"""Carries the camera thread's news to the UI thread as Qt signals."""
import threading

from PySide6.QtCore import QObject, Signal

from ..calibration import CalibrationStatus
from ..gestures import GestureEvent
from ..tracking_loop import FrameView, Status


class TrackingBridge(QObject):
    """A TrackingListener whose methods, called on the camera thread, emit signals handled on the UI thread.

    Frames aren't queued: if the UI hasn't taken the last one yet, a newer one replaces it, so a
    busy UI shows the newest frame rather than falling behind.
    """

    status_changed = Signal(object)  # Status
    frame_ready = Signal()  # take it with take_frame()
    gesture_detected = Signal(object, str)  # GestureEvent, description
    calibration_changed = Signal(object)  # CalibrationStatus

    def __init__(self):
        super().__init__()
        self._frame_lock = threading.Lock()
        self._latest_frame: FrameView | None = None
        self._frame_signaled = False

    def take_frame(self) -> FrameView | None:
        with self._frame_lock:
            self._frame_signaled = False
            return self._latest_frame

    def on_status(self, status: Status):
        self.status_changed.emit(status)

    def on_frame(self, view: FrameView):
        with self._frame_lock:
            self._latest_frame = view
            signal = not self._frame_signaled
            self._frame_signaled = True
        if signal:
            self.frame_ready.emit()

    def on_gesture(self, event: GestureEvent, description: str):
        self.gesture_detected.emit(event, description)

    def on_calibration(self, status: CalibrationStatus):
        self.calibration_changed.emit(status)
