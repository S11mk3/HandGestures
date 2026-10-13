"""The small always-on-top window showing the camera image, the tracked hands and the last action."""
from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..tracking_loop import FrameView
from .camera_view import CameraView

DEFAULT_SIZE = (320, 240)
SCREEN_EDGE_MARGIN = 20


class PreviewWindow(QWidget):
    """A tool window: it stays above other windows but out of the taskbar and Alt+Tab (otherwise
    Alt+Tab would just switch to the preview), and never takes focus from the app being controlled."""

    closed = Signal()  # by the user, with its X button

    def __init__(self, window_state: QSettings):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self._window_state = window_state
        self.setWindowTitle("HandGestures")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.camera_view = CameraView(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.camera_view)
        if not self.restoreGeometry(window_state.value("preview/geometry", b"")):
            self._place_at_default_position()

    def set_view(self, view: FrameView):
        self.camera_view.set_view(view)

    def hideEvent(self, event):
        self._window_state.setValue("preview/geometry", self.saveGeometry())
        super().hideEvent(event)

    def closeEvent(self, event):
        super().closeEvent(event)
        self.closed.emit()

    def _place_at_default_position(self):
        """Vertically centered at the left edge of the main screen, clear of the taskbar."""
        self.resize(*DEFAULT_SIZE)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.left() + SCREEN_EDGE_MARGIN, screen.top() + (screen.height() - DEFAULT_SIZE[1]) // 2)
