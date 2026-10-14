"""A widget showing camera frames, with the tracked hands and status labels drawn over them."""
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..hand_landmarks import HAND_CONNECTIONS
from ..tracking_loop import FrameView

BONE_COLOR = QColor(255, 255, 255, 220)
JOINT_COLOR = QColor(60, 200, 90)
LABEL_BACKGROUND = QColor(0, 0, 0, 160)
ACTION_BACKGROUND = QColor(45, 125, 210, 230)
PAUSED_BACKGROUND = QColor(180, 40, 40, 230)


class CameraView(QWidget):
    """Call set_view() with each new frame. The image keeps its aspect ratio, letterboxed in black."""

    def __init__(self, parent: QWidget | None = None, show_labels: bool = True):
        super().__init__(parent)
        self.show_labels = show_labels
        self.show_details = False
        self.placeholder = "Starting the camera…"
        self._view: FrameView | None = None
        self.setMinimumSize(160, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_view(self, view: FrameView | None):
        self._view = view
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("black"))
        view = self._view
        if view is None:
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.placeholder)
            return
        image_rect = self._draw_image(painter, view.image)
        self._draw_hands(painter, view, image_rect)
        if self.show_labels:
            self._draw_labels(painter, view, image_rect)
        self.paint_overlay(painter, image_rect)

    def paint_overlay(self, painter: QPainter, image_rect: QRectF):
        """Subclasses draw extras over the image here."""

    def _draw_image(self, painter: QPainter, image: np.ndarray) -> QRectF:
        image = np.ascontiguousarray(image)
        height, width = image.shape[:2]
        scale = min(self.width() / width, self.height() / height)
        target = QRectF(0, 0, width * scale, height * scale)
        target.moveCenter(QRectF(self.rect()).center())
        # The QImage shares the array's memory, which stays alive until painting is done.
        painter.drawImage(target, QImage(image.data, width, height, image.strides[0], QImage.Format.Format_BGR888))
        return target

    def _draw_hands(self, painter: QPainter, view: FrameView, image_rect: QRectF):
        line_width = max(image_rect.width() / 320, 1.5)
        for hand in view.hands:
            points = [QPointF(image_rect.left() + x * image_rect.width(), image_rect.top() + y * image_rect.height())
                      for x, y, _ in hand.image]
            painter.setPen(QPen(BONE_COLOR, line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for start, end in HAND_CONNECTIONS:
                painter.drawLine(points[start], points[end])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(JOINT_COLOR)
            for point in points:
                painter.drawEllipse(point, line_width * 1.6, line_width * 1.6)

    def _draw_labels(self, painter: QPainter, view: FrameView, image_rect: QRectF):
        font = QFont(self.font())
        font.setPixelSize(max(int(image_rect.height() / 18), 11))
        margin = font.pixelSize() * 0.5
        top_left = QPointF(image_rect.left() + margin, image_rect.top() + margin)
        draw_pill(painter, view.pose_label, top_left, font, LABEL_BACKGROUND)
        if view.last_action:
            top_right = QPointF(image_rect.right() - margin, image_rect.top() + margin)
            draw_pill(painter, view.last_action, top_right, font, ACTION_BACKGROUND, align_right=True)
        bottom = image_rect.bottom() - margin
        if view.paused:
            pill = draw_pill(painter, "Paused — click the tray icon to resume",
                             QPointF(image_rect.left() + margin, bottom), font, PAUSED_BACKGROUND, align_bottom=True)
            bottom = pill.top() - margin / 2
        if self.show_details and view.details:
            small = QFont(font)
            small.setPixelSize(max(int(font.pixelSize() * 0.75), 10))
            draw_pill(painter, view.details, QPointF(image_rect.left() + margin, bottom), small, LABEL_BACKGROUND,
                      align_bottom=True)


def draw_pill(painter: QPainter, text: str, anchor: QPointF, font: QFont, background: QColor,
              align_right: bool = False, align_bottom: bool = False) -> QRectF:
    """Draw text on a rounded label whose top-left (or other) corner is at anchor; return its rectangle."""
    metrics = QFontMetricsF(font)
    padding = font.pixelSize() * 0.45
    rect = QRectF(0, 0, metrics.horizontalAdvance(text) + 2 * padding, metrics.height() + padding)
    rect.moveTopLeft(anchor)
    if align_right:
        rect.moveRight(anchor.x())
    if align_bottom:
        rect.moveBottom(anchor.y())
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(background)
    painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()
    return rect
