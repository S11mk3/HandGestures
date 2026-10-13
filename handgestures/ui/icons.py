"""The app icon, a white open hand on a colored circle, drawn in the color of each status."""
from enum import Enum

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)


class IconState(Enum):
    ACTIVE = QColor(46, 160, 67)  # green
    PAUSED = QColor(140, 140, 140)  # gray
    CALIBRATING = QColor(45, 125, 210)  # blue
    PROBLEM = QColor(214, 138, 0)  # amber


def draw_icon(color: QColor, size: int) -> QImage:
    """The icon at size x size pixels. Drawn on a 64-unit grid, scaled."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 64, size / 64)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QRectF(2, 2, 60, 60))
    painter.setBrush(QColor("white"))
    painter.drawRoundedRect(QRectF(18, 29, 24, 24), 7, 7)  # palm
    # Index, middle, ring and pinky: (left, top, width), with gaps between them.
    for left, top, width in ((18, 15, 5.2), (24.2, 11, 5.2), (30.4, 13, 5.2), (36.6, 18, 5.0)):
        painter.drawRoundedRect(QRectF(left, top, width, 36 - top), width / 2, width / 2)
    painter.translate(39, 41)  # the thumb, angled out from the side of the palm
    painter.rotate(-40)
    painter.drawRoundedRect(QRectF(0, -2.8, 14, 5.6), 2.8, 2.8)
    painter.end()
    return image


def status_icon(state: IconState) -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(QPixmap.fromImage(draw_icon(state.value, size)))
    return icon


def app_icon() -> QIcon:
    return status_icon(IconState.ACTIVE)
