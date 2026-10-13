"""Starts HandGestures: the tray icon and windows on the main thread, the camera on a background thread."""
import argparse
import getpass
import logging
import os
import sys

import win32api
import win32event
import winerror
from PySide6.QtCore import QObject, QSettings, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import __copyright__, __version__
from .actions import ActionRunner
from .app_state import AppState
from .calibration import CalibrationStatus
from .config import ConfigStore
from .gestures import GestureEvent
from .logging_setup import setup_logging
from .paths import APP_DIR, DATA_DIR, LOG_PATH, WINDOW_STATE_PATH
from .pointer_driver import Win32Cursor
from .tracking_loop import Status, StatusKind, TrackingLoop
from .ui.bridge import TrackingBridge
from .ui.calibration_window import CalibrationWindow
from .ui.guide_window import GuideWindow
from .ui.icons import app_icon
from .ui.preview_window import PreviewWindow
from .ui.settings_window import SettingsWindow
from .ui.tray import Tray

# The installer checks for this mutex too, to ask the user to quit the app before updating it.
SINGLE_INSTANCE_MUTEX_NAME = "HandGesturesRunning"
# A second copy tells the running one, through this local socket, to open its settings.
INSTANCE_SERVER_NAME = f"HandGestures-{getpass.getuser()}"

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Control Windows with hand gestures.")
    parser.add_argument("--dry-run", action="store_true", help="log gestures without performing actions")
    parser.add_argument("--no-preview", action="store_true", help="start with the camera preview hidden")
    parser.add_argument("--no-calibration", action="store_true", help="skip calibration this time")
    parser.add_argument("--verbose", action="store_true", help="log debugging details")
    return parser.parse_args()


def acquire_single_instance_lock():
    """Return a handle to keep open until exit, or None if HandGestures is already running.

    A second copy would fight over the camera and perform every action twice.
    """
    mutex = win32event.CreateMutex(None, False, SINGLE_INSTANCE_MUTEX_NAME)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        return None
    return mutex


def notify_running_instance():
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_SERVER_NAME)
    if socket.waitForConnected(1000):
        socket.write(b"show-settings")
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()


class AppController(QObject):
    """Owns the windows, the tray icon and the camera thread, and connects them."""

    def __init__(self, args: argparse.Namespace):
        super().__init__()
        self._store = ConfigStore()
        config = self._store.config
        self._state = AppState()
        self._bridge = TrackingBridge()
        self._window_state = QSettings(str(WINDOW_STATE_PATH), QSettings.Format.IniFormat)
        self._calibrate_at_start = config.calibrate_on_start and not args.no_calibration
        self._preview_wanted = config.show_preview_on_start and not args.no_preview
        self._status = Status(StatusKind.STARTING, "Starting…")
        self._notified_problems: set[str] = set()
        self._loop = TrackingLoop(self._store, self._state, self._bridge, ActionRunner(args.dry_run),
                                  None if args.dry_run else Win32Cursor(), self._calibrate_at_start)

        self._preview: PreviewWindow | None = None
        self._calibration_window: CalibrationWindow | None = None
        self._settings_window: SettingsWindow | None = None
        self._guide_window: GuideWindow | None = None

        self._tray = Tray()
        self._tray.pause_toggled.connect(self.toggle_pause)
        self._tray.preview_toggled.connect(self.set_preview_visible)
        self._tray.recalibrate_requested.connect(self.recalibrate)
        self._tray.settings_requested.connect(self.show_settings)
        self._tray.guide_requested.connect(self.show_guide)
        self._tray.data_folder_requested.connect(lambda: os.startfile(DATA_DIR))
        self._tray.about_requested.connect(self.show_about)
        self._tray.quit_requested.connect(QApplication.quit)

        self._bridge.status_changed.connect(self._on_status)
        self._bridge.frame_ready.connect(self._on_frame)
        self._bridge.gesture_detected.connect(self._on_gesture)
        self._bridge.calibration_changed.connect(self._on_calibration)
        self._store.subscribe(lambda config: self._on_settings_changed())

        self._instance_server = QLocalServer(self)
        QLocalServer.removeServer(INSTANCE_SERVER_NAME)
        self._instance_server.newConnection.connect(self._on_second_instance)
        if not self._instance_server.listen(INSTANCE_SERVER_NAME):
            log.warning("Could not listen for other instances: %s", self._instance_server.errorString())

    def start(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.show()
        else:
            self._preview_wanted = True  # without a tray icon, the preview is the only sign the app runs
        self._loop.start()
        if self._calibrate_at_start:
            self._show_calibration_window()
        else:
            self._after_calibration()
        self._update_tray()

    def shutdown(self):
        self._loop.stop()
        self._tray.hide()

    # Tray menu

    def toggle_pause(self):
        self._state.paused = not self._state.paused
        log.info("Paused" if self._state.paused else "Resumed")
        self._update_tray()

    def set_preview_visible(self, visible: bool):
        self._preview_wanted = visible
        if visible:
            if self._preview is None:
                self._preview = PreviewWindow(self._window_state)
                self._preview.closed.connect(lambda: self.set_preview_visible(False))
            self._preview.camera_view.show_details = self._store.config.show_debug_info
            self._preview.show()
        elif self._preview is not None:
            self._preview.hide()
        self._update_frames_wanted()
        self._update_tray()

    def recalibrate(self):
        self._state.calibration_requested.set()
        self._show_calibration_window()

    def show_settings(self):
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self._store)
            self._settings_window.setWindowIcon(app_icon())
            self._settings_window.recalibrate_requested.connect(self.recalibrate)
            self._settings_window.guide_requested.connect(self.show_guide)
        _bring_up(self._settings_window)

    def show_guide(self):
        if self._guide_window is None:
            self._guide_window = GuideWindow()
            self._guide_window.practice_mode_changed.connect(lambda checked: self._update_practice_mode())
            self._guide_window.visibility_changed.connect(lambda visible: self._update_practice_mode())
        self._guide_window.show_actions(self._store.config)
        _bring_up(self._guide_window)

    def show_about(self):
        notices = (APP_DIR / "THIRD_PARTY_NOTICES.md").as_uri()
        QMessageBox.about(
            None, "About HandGestures",
            f"<h3>HandGestures {__version__}</h3>"
            "<p>Control Windows with hand gestures through your webcam.</p>"
            "<p>Hand tracking runs on this PC. The camera image never leaves it and is never saved.</p>"
            f"<p>Settings, calibration and log: <a href='{DATA_DIR.as_uri()}'>{DATA_DIR}</a></p>"
            f"<p>Built with MediaPipe, OpenCV and Qt. <a href='{notices}'>Third-party notices</a></p>"
            f"<p>{__copyright__}</p>")

    # News from the camera thread

    def _on_status(self, status: Status):
        self._status = status
        self._update_tray()
        if status.kind is StatusKind.PROBLEM:
            if status.message not in self._notified_problems:
                self._notified_problems.add(status.message)
                self._tray.notify(status.message, warning=True)
        elif status.kind is StatusKind.RUNNING:
            self._notified_problems.clear()

    def _on_frame(self):
        view = self._bridge.take_frame()
        if view is None:
            return
        for window in (self._preview, self._calibration_window, self._guide_window):
            if window is not None and window.isVisible():
                window.set_view(view)

    def _on_gesture(self, event: GestureEvent, description: str):
        if self._guide_window is not None and self._guide_window.isVisible():
            self._guide_window.flash(event.gesture)

    def _on_calibration(self, status: CalibrationStatus):
        window = self._calibration_window
        if window is not None and window.isVisible():
            window.show_status(status)

    def _on_settings_changed(self):
        config = self._store.config
        if self._preview is not None:
            self._preview.camera_view.show_details = config.show_debug_info
        if self._guide_window is not None:
            self._guide_window.show_actions(config)

    def _on_second_instance(self):
        socket = self._instance_server.nextPendingConnection()
        if socket is not None:
            socket.disconnected.connect(socket.deleteLater)
        self.show_settings()

    # Calibration and first run

    def _show_calibration_window(self):
        if self._calibration_window is None:
            self._calibration_window = CalibrationWindow()
            self._calibration_window.setWindowIcon(app_icon())
            self._calibration_window.skip_requested.connect(self._state.calibration_skip_requested.set)
            self._calibration_window.finished.connect(self._after_calibration)
        if self._preview is not None:
            self._preview.hide()  # one camera view at a time
        self._calibration_window.start()
        self._update_frames_wanted()

    def _after_calibration(self):
        self._update_frames_wanted()
        if self._preview_wanted:
            self.set_preview_visible(True)
        if not self._store.config.first_run_done:
            self._store.update(first_run_done=True)
            self._tray.notify("HandGestures is running. Click its icon in the tray to pause, "
                              "or right-click it for settings.")
            QTimer.singleShot(500, self.show_guide)

    # Helpers

    def _update_tray(self):
        self._tray.update(self._status, self._state.paused, self._preview is not None and self._preview.isVisible())

    def _update_frames_wanted(self):
        windows = (self._preview, self._calibration_window, self._guide_window)
        self._state.frames_wanted = any(window is not None and window.isVisible() for window in windows)

    def _update_practice_mode(self):
        guide = self._guide_window
        self._state.practice_mode = guide is not None and guide.isVisible() and guide.practice.isChecked()
        self._update_frames_wanted()


def _bring_up(window):
    window.show()
    window.raise_()
    window.activateWindow()


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    # Creating the QApplication makes the process DPI aware (per monitor), so cursor positions
    # and screen sizes are in physical pixels: it must come before any of those are read.
    app = QApplication(sys.argv)
    app.setApplicationName("HandGestures")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)  # the tray icon keeps it running
    app.setWindowIcon(app_icon())

    instance_lock = acquire_single_instance_lock()  # released when the process exits
    if instance_lock is None:
        log.info("HandGestures is already running; asking it to show its settings")
        notify_running_instance()
        return 0

    try:
        controller = AppController(args)
        controller.start()
    except Exception as error:
        log.exception("Could not start")
        QMessageBox.critical(None, "HandGestures",
                             f"HandGestures couldn't start:\n{error}\n\nDetails are in {LOG_PATH}.")
        return 1
    try:
        return app.exec()
    finally:
        controller.shutdown()
        log.info("Quit")
