"""The window shown while calibrating: live camera image, what to do, and any problems found."""
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..calibration import CalibrationStatus, Step
from ..tracking_loop import FrameView
from .camera_view import CameraView

RESULT_DISPLAY_MS = 2500  # how long the result stays up when all went well
RESULT_WITH_ADVICE_DISPLAY_MS = 12000  # ...and when there's advice to read
RING_COLOR = QColor(45, 125, 210)
DONE_COLOR = QColor(46, 160, 67)
WARNING_COLOR = QColor(214, 138, 0)
STEP_NAMES = {Step.LIGHT: "Step 1 of 2: checking the light", Step.HAND: "Step 2 of 2: measuring your hand",
              Step.DONE: "Done"}


class _CalibrationCameraView(CameraView):
    """The camera image with a progress ring in the middle."""

    def __init__(self, parent: QWidget):
        super().__init__(parent, show_labels=False)
        self.status: CalibrationStatus | None = None

    def paint_overlay(self, painter: QPainter, image_rect: QRectF):
        status = self.status
        if status is None:
            return
        radius = min(image_rect.width(), image_rect.height()) * 0.16
        center = image_rect.center()
        ring = QRectF(center - QPointF(radius, radius), center + QPointF(radius, radius))
        width = radius * 0.16
        painter.setPen(QPen(QColor(255, 255, 255, 90), width))
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.drawEllipse(ring)
        if status.step is Step.DONE:
            color = DONE_COLOR if status.hand_measured else WARNING_COLOR
            symbol = "✓" if status.hand_measured else "!"
        else:
            color = RING_COLOR
            symbol = "☀" if status.step is Step.LIGHT else "✋"
        painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(ring, 90 * 16, -int(360 * 16 * status.progress))
        font = QFont(self.font())
        font.setPixelSize(int(radius * 0.9))
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(ring, Qt.AlignmentFlag.AlignCenter, symbol)


class CalibrationWindow(QWidget):
    """Call show_status() with each calibration update. Emits `finished` once the result has been shown."""

    skip_requested = Signal()
    finished = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Hard2Gesture — Getting ready")
        # Shown at sign-in too: it mustn't take the keyboard from whatever the user is doing.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._done = False
        self._finish_timer = QTimer(self, singleShot=True, timeout=self._finish)

        title = QLabel("Getting ready")
        title_font = title.font()
        title_font.setPointSizeF(title_font.pointSizeF() * 1.6)
        title_font.setBold(True)
        title.setFont(title_font)
        self._step_label = QLabel()
        self._step_label.setStyleSheet("color: palette(placeholder-text);")
        self._camera_view = _CalibrationCameraView(self)
        self._camera_view.setMinimumSize(480, 360)
        self._instruction = QLabel("Starting the camera…")
        self._instruction.setWordWrap(True)
        instruction_font = self._instruction.font()
        instruction_font.setPointSizeF(instruction_font.pointSizeF() * 1.25)
        self._instruction.setFont(instruction_font)
        self._advice = QLabel()
        self._advice.setWordWrap(True)
        self._advice.setTextFormat(Qt.TextFormat.RichText)
        self._advice.hide()
        self._button = QPushButton("Skip")
        self._button.clicked.connect(self._on_button)

        buttons = QHBoxLayout()
        buttons.addWidget(self._step_label, 1)
        buttons.addWidget(self._button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(self._camera_view, 1)
        layout.addWidget(self._instruction)
        layout.addWidget(self._advice)
        layout.addLayout(buttons)

    def start(self):
        """Show the window for a new calibration."""
        self._done = False
        self._finish_timer.stop()
        self._camera_view.status = None
        self._camera_view.set_view(None)
        self._instruction.setText("Starting the camera…")
        self._advice.hide()
        self._button.setText("Skip")
        self._step_label.setText("")
        self.adjustSize()
        self._center_on_screen()
        self.show()
        self.raise_()

    def set_view(self, view: FrameView):
        self._camera_view.set_view(view)

    def show_status(self, status: CalibrationStatus):
        if self._done:
            return
        self._camera_view.status = status
        self._camera_view.update()
        self._instruction.setText(status.instruction)
        self._step_label.setText(STEP_NAMES[status.step])
        if status.advice:
            items = "".join(f"<li>{text}</li>" for text in status.advice)
            self._advice.setText(f"<span style='color:#b26b00'>⚠</span> <b>Tips</b><ul style='margin:0'>{items}</ul>")
            self._advice.show()
        else:
            self._advice.hide()
        if status.step is Step.DONE:
            self._done = True
            self._button.setText("Close")
            self._finish_timer.start(RESULT_WITH_ADVICE_DISPLAY_MS if status.advice else RESULT_DISPLAY_MS)

    def _on_button(self):
        if self._done:
            self._finish()
        else:
            self.skip_requested.emit()

    def _finish(self):
        self._finish_timer.stop()
        self.hide()
        self.finished.emit()

    def closeEvent(self, event):
        super().closeEvent(event)
        if self._done:
            self._finish_timer.stop()
            self.finished.emit()
        else:
            self.skip_requested.emit()  # the result arrives, and is dismissed, as for Skip
            self._done = True
            self.finished.emit()

    def _center_on_screen(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(screen.center())
        self.move(frame.topLeft())
