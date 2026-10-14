"""The gesture guide: every gesture and what it does, with a live camera view to practice in."""
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..bindings import ACTIONS, action_for
from ..config import Config
from ..gestures import Gesture
from ..tracking_loop import FrameView
from .camera_view import CameraView

FLASH_MS = 900  # how long a card lights up when its gesture is recognized


@dataclass(frozen=True)
class GuideCard:
    symbol: str
    title: str
    how: str
    gesture: Gesture | None = None  # lights up the card when recognized
    pose: str = ""  # or: lights up the card while the hand holds this pose
    action: str = ""  # what it does, for gestures whose action can't be changed


CARDS = (
    GuideCard("☝", "Point", "Point with your index finger and move your hand. To reposition your hand, "
              "stop pointing, move, and point again.", pose="pointing", action="Move the pointer"),
    GuideCard("🤏", "Pinch", "While pointing, tap your thumb against your index finger.",
              Gesture.PINCH, action="Click"),
    GuideCard("🤏🤏", "Double pinch", "Pinch twice, quickly.", Gesture.DOUBLE_PINCH, action="Double click"),
    GuideCard("✌", "Two fingers", "Hold up your index and middle fingers and move them up or down.",
              Gesture.SCROLL, action="Scroll"),
    GuideCard("✋⬅", "Swipe left", "Swipe an open palm to the left.", Gesture.SWIPE_LEFT),
    GuideCard("✋➡", "Swipe right", "Swipe an open palm to the right.", Gesture.SWIPE_RIGHT),
    GuideCard("✋⬆", "Swipe up", "Swipe an open palm upward.", Gesture.SWIPE_UP),
    GuideCard("✋⬇", "Swipe down", "Swipe an open palm downward.", Gesture.SWIPE_DOWN),
    GuideCard("✊", "Hold a fist", "Hold a still fist for a moment.", Gesture.FIST_HOLD),
    GuideCard("👐↔", "Palms apart", "Hold up two open palms and move them apart.", Gesture.HANDS_APART),
    GuideCard("👐→←", "Palms together", "Hold up two open palms and move them together.", Gesture.HANDS_TOGETHER),
)


class _Card(QFrame):
    def __init__(self, card: GuideCard):
        super().__init__()
        self.card = card
        self.setObjectName("card")
        self._lit = False
        self._active = False
        symbol = QLabel(card.symbol)
        symbol_font = symbol.font()
        symbol_font.setPointSizeF(symbol_font.pointSizeF() * 2.2)
        symbol.setFont(symbol_font)
        symbol.setFixedWidth(84)
        symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(f"<b>{card.title}</b>")
        how = QLabel(card.how)
        how.setWordWrap(True)
        self._action = QLabel()
        self._action.setStyleSheet("color: palette(link);")
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(title)
        text.addWidget(how)
        text.addWidget(self._action)
        layout = QHBoxLayout(self)
        layout.addWidget(symbol)
        layout.addLayout(text, 1)
        self._timer = QTimer(self, singleShot=True, interval=FLASH_MS, timeout=self._unflash)
        self._restyle()

    def show_action(self, config: Config):
        action = self.card.action or ACTIONS[action_for(self.card.gesture, config.gesture_actions)].name
        self._action.setText(f"→ {action}")

    def flash(self):
        self._lit = True
        self._restyle()
        self._timer.start()

    def set_active(self, active: bool):
        if active != self._active:
            self._active = active
            self._restyle()

    def _unflash(self):
        self._lit = False
        self._restyle()

    def _restyle(self):
        if self._lit:
            border = "2px solid palette(highlight); background: palette(alternate-base)"
        elif self._active:
            border = "2px dashed palette(highlight)"
        else:
            border = "1px solid palette(mid)"
        self.setStyleSheet(f"QFrame#card {{ border: {border}; border-radius: 8px; }}")


class GuideWindow(QWidget):
    """Lists the gestures; recognized gestures light up their card. In practice mode the app
    recognizes gestures but doesn't act on them, so they can be tried safely."""

    practice_mode_changed = Signal(bool)
    visibility_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hard2Gesture — Gesture guide")
        title = QLabel("Gestures")
        title_font = title.font()
        title_font.setPointSizeF(title_font.pointSizeF() * 1.6)
        title_font.setBold(True)
        title.setFont(title_font)
        intro = QLabel("Make gestures in front of the camera, about an arm's length away. "
                       "Each one lights up here when it's recognized.")
        intro.setWordWrap(True)
        self.practice = QCheckBox("Practice mode (actions are off)")
        self.practice.setToolTip("Recognize gestures, but don't perform their actions")
        self.practice.setChecked(True)
        self.practice.toggled.connect(self.practice_mode_changed)
        self.camera_view = CameraView(self)
        self.camera_view.setFixedSize(320, 240)

        self._cards = [_Card(card) for card in CARDS]
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, card in enumerate(self._cards):
            grid.addWidget(card, i // 2, i % 2)

        left = QVBoxLayout()
        left.addWidget(self.camera_view)
        left.addWidget(self.practice)
        left.addStretch(1)
        body = QHBoxLayout()
        body.addLayout(left)
        body.addLayout(grid, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addLayout(body)

    def show_actions(self, config: Config):
        for card in self._cards:
            card.show_action(config)

    def set_view(self, view: FrameView):
        self.camera_view.set_view(view)
        for card in self._cards:
            if card.card.pose:
                card.set_active(view.pose_label == card.card.pose)

    def flash(self, gesture: Gesture):
        for card in self._cards:
            if card.card.gesture is gesture:
                card.flash()

    def showEvent(self, event):
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibility_changed.emit(False)
