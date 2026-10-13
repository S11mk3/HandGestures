"""The settings window. Every change applies and is saved right away."""
import logging
import os
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import autostart
from ..bindings import ACTIONS, BINDABLE_GESTURES
from ..calibration import load_profile
from ..camera import camera_names
from ..config import Config, ConfigStore
from ..gestures import Gesture

log = logging.getLogger(__name__)

SLIDER_STEPS = 100
SAVE_DELAY_MS = 300  # a dragged slider saves once it stops moving
END_LABEL_WIDTH = 48

GESTURE_NAMES = {
    Gesture.SWIPE_LEFT: "✋ Swipe left",
    Gesture.SWIPE_RIGHT: "✋ Swipe right",
    Gesture.SWIPE_UP: "✋ Swipe up",
    Gesture.SWIPE_DOWN: "✋ Swipe down",
    Gesture.FIST_HOLD: "✊ Hold a fist",
    Gesture.HANDS_APART: "👐 Move two palms apart",
    Gesture.HANDS_TOGETHER: "👐 Move two palms together",
}


class SliderRow(QWidget):
    """A slider for a number setting between low and high, with labels at its ends and its value."""

    committed = Signal(float)

    def __init__(self, low: float, high: float, format_value: Callable[[float], str],
                 low_label: str = "", high_label: str = ""):
        super().__init__()
        self._low, self._high = low, high
        self._format_value = format_value
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, SLIDER_STEPS)
        self._value_label = QLabel()
        self._value_label.setMinimumWidth(56)
        self._save_timer = QTimer(self, singleShot=True, interval=SAVE_DELAY_MS,
                                  timeout=lambda: self.committed.emit(self.value()))
        self._slider.valueChanged.connect(self._on_moved)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Fixed-width end labels, even empty ones, so every slider starts and ends at the same place.
        for text, alignment, widget in ((low_label, Qt.AlignmentFlag.AlignRight, None),
                                        (None, None, self._slider),
                                        (high_label, Qt.AlignmentFlag.AlignLeft, None)):
            if widget is None:
                widget = QLabel(text)
                widget.setFixedWidth(END_LABEL_WIDTH)
                widget.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(widget, 1 if widget is self._slider else 0)
        layout.addWidget(self._value_label)

    def value(self) -> float:
        return self._low + (self._high - self._low) * self._slider.value() / SLIDER_STEPS

    def set_value(self, value: float):
        """Show a value without saving it."""
        self._slider.blockSignals(True)
        self._slider.setValue(round((value - self._low) / (self._high - self._low) * SLIDER_STEPS))
        self._slider.blockSignals(False)
        self._value_label.setText(self._format_value(value))

    def _on_moved(self):
        self._value_label.setText(self._format_value(self.value()))
        self._save_timer.start()


class SettingsWindow(QWidget):
    recalibrate_requested = Signal()
    guide_requested = Signal()

    def __init__(self, store: ConfigStore):
        super().__init__()
        self._store = store
        self.setWindowTitle("HandGestures Settings")
        self.setMinimumWidth(560)

        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._gestures_tab(), "Gestures")
        tabs.addTab(self._pointer_tab(), "Pointer")
        tabs.addTab(self._camera_tab(), "Camera")

        open_file = QPushButton("Open settings file")
        open_file.clicked.connect(lambda: os.startfile(store.path))
        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self._reset)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addWidget(open_file)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addLayout(buttons)
        store.subscribe(lambda config: self._show_values(config))
        self._show_values(store.config)

    def showEvent(self, event):
        self._show_values(self._store.config)
        self._refresh_cameras()
        self._calibration_label.setText(_calibration_summary())
        super().showEvent(event)

    # Tabs

    def _general_tab(self) -> QWidget:
        self._autostart = QCheckBox("Start HandGestures when I sign in to Windows")
        self._autostart.toggled.connect(self._set_autostart)
        self._calibrate_on_start = self._checkbox("Calibrate every time HandGestures starts", "calibrate_on_start")
        self._show_preview_on_start = self._checkbox("Show the camera preview when HandGestures starts",
                                                     "show_preview_on_start")
        self._battery_saver = self._checkbox("Battery saver: look for hands less often while none are in view",
                                             "battery_saver")
        guide = QPushButton("Show the gesture guide")
        guide.clicked.connect(self.guide_requested)
        tab, layout = _tab()
        for widget in (self._autostart, self._calibrate_on_start, self._show_preview_on_start, self._battery_saver):
            layout.addWidget(widget)
        layout.addSpacing(12)
        layout.addWidget(guide, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return tab

    def _gestures_tab(self) -> QWidget:
        tab, layout = _tab()
        form = QFormLayout()
        self._action_boxes: dict[Gesture, QComboBox] = {}
        for gesture in BINDABLE_GESTURES:
            box = QComboBox()
            for action_id, info in ACTIONS.items():
                box.addItem(info.name, action_id)
            box.currentIndexChanged.connect(self._save_gesture_actions)
            self._action_boxes[gesture] = box
            form.addRow(GESTURE_NAMES[gesture], box)
        layout.addLayout(form)
        layout.addSpacing(8)
        self._scroll_enabled = self._checkbox("✌ Scroll by moving two fingers up or down", "scroll_enabled")
        layout.addWidget(self._scroll_enabled)
        tuning = QFormLayout()
        self._scroll_amount = self._slider("scroll_amount", 30, 480, lambda v: f"{v / 120:.2g} notch", round)
        self._swipe_distance = self._slider("swipe_distance", 0.12, 0.40, lambda v: "", low_label="Short",
                                            high_label="Long")
        self._fist_hold = self._slider("fist_hold_s", 0.5, 2.5, lambda v: f"{v:.1f} s")
        tuning.addRow("Scroll speed", self._scroll_amount)
        tuning.addRow("Swipe length", self._swipe_distance)
        tuning.addRow("Fist hold time", self._fist_hold)
        layout.addLayout(tuning)
        layout.addStretch(1)
        return tab

    def _pointer_tab(self) -> QWidget:
        tab, layout = _tab()
        self._pointer_enabled = self._checkbox("☝ Move the pointer by pointing, and 🤏 click by pinching",
                                               "pointer_enabled")
        layout.addWidget(self._pointer_enabled)
        form = QFormLayout()
        self._pointer_speed = self._slider("pointer_speed", 0.3, 3.0, lambda v: f"{v:.1f}x", low_label="Slow",
                                           high_label="Fast")
        self._pointer_acceleration = self._slider("pointer_acceleration", 0.0, 3.0, lambda v: "",
                                                  low_label="Off", high_label="Strong")
        self._pointer_smoothing = self._slider("pointer_smoothing", 0.25, 4.0, lambda v: "",
                                               low_label="Quick", high_label="Steady")
        # A larger pinch_distance clicks with fingertips farther apart: a lighter pinch.
        self._pinch_distance = self._slider("pinch_distance", 0.15, 0.5, lambda v: "",
                                            low_label="Firm", high_label="Light")
        form.addRow("Speed", self._pointer_speed)
        form.addRow("Acceleration", self._pointer_acceleration)
        form.addRow("Smoothing", self._pointer_smoothing)
        form.addRow("Pinch to click", self._pinch_distance)
        layout.addLayout(form)
        hint = QLabel("To move your hand without moving the pointer, stop pointing, move, and point again.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(hint)
        layout.addStretch(1)
        return tab

    def _camera_tab(self) -> QWidget:
        tab, layout = _tab()
        self._camera_box = QComboBox()
        self._camera_box.currentIndexChanged.connect(self._save_camera)
        form = QFormLayout()
        form.addRow("Camera", self._camera_box)
        layout.addLayout(form)
        self._calibration_label = QLabel()
        self._calibration_label.setWordWrap(True)
        recalibrate = QPushButton("Recalibrate now")
        recalibrate.clicked.connect(self.recalibrate_requested)
        layout.addWidget(self._calibration_label)
        layout.addWidget(recalibrate, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(12)
        self._show_debug_info = self._checkbox("Show tracking details on the camera preview", "show_debug_info")
        layout.addWidget(self._show_debug_info)
        layout.addStretch(1)
        return tab

    # Building blocks

    def _checkbox(self, text: str, setting: str) -> QCheckBox:
        checkbox = QCheckBox(text)
        checkbox.toggled.connect(lambda checked: self._store.update(**{setting: checked}))
        return checkbox

    def _slider(self, setting: str, low: float, high: float, format_value: Callable[[float], str],
                convert: Callable[[float], float] = float, low_label: str = "", high_label: str = "") -> SliderRow:
        row = SliderRow(low, high, format_value, low_label, high_label)
        row.committed.connect(lambda value: self._store.update(**{setting: convert(value)}))
        return row

    # Showing and saving values

    def _show_values(self, config: Config):
        checkboxes = {
            self._calibrate_on_start: config.calibrate_on_start,
            self._show_preview_on_start: config.show_preview_on_start,
            self._battery_saver: config.battery_saver,
            self._scroll_enabled: config.scroll_enabled,
            self._pointer_enabled: config.pointer_enabled,
            self._show_debug_info: config.show_debug_info,
            self._autostart: autostart.is_enabled(),
        }
        for checkbox, checked in checkboxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)
        for gesture, box in self._action_boxes.items():
            box.blockSignals(True)
            box.setCurrentIndex(max(box.findData(config.gesture_actions.get(gesture.value)), 0))
            box.blockSignals(False)
        sliders = {
            self._scroll_amount: config.scroll_amount,
            self._swipe_distance: config.swipe_distance,
            self._fist_hold: config.fist_hold_s,
            self._pointer_speed: config.pointer_speed,
            self._pointer_acceleration: config.pointer_acceleration,
            self._pointer_smoothing: config.pointer_smoothing,
            self._pinch_distance: config.pinch_distance,
        }
        for slider, value in sliders.items():
            slider.set_value(value)
        for widget in (self._pointer_speed, self._pointer_acceleration, self._pointer_smoothing, self._pinch_distance):
            widget.setEnabled(config.pointer_enabled)
        self._scroll_amount.setEnabled(config.scroll_enabled)

    def _save_gesture_actions(self):
        self._store.update(gesture_actions={gesture.value: box.currentData()
                                            for gesture, box in self._action_boxes.items()})

    def _refresh_cameras(self):
        names = camera_names()
        count = max(len(names), self._store.config.camera_index + 1, 1)
        self._camera_box.blockSignals(True)
        self._camera_box.clear()
        for index in range(count):
            name = names[index] if index < len(names) else "Camera"
            self._camera_box.addItem(f"{index + 1}: {name}", index)
        self._camera_box.setCurrentIndex(self._store.config.camera_index)
        self._camera_box.blockSignals(False)

    def _save_camera(self):
        index = self._camera_box.currentData()
        if index is not None:
            self._store.update(camera_index=index)

    def _set_autostart(self, enabled: bool):
        try:
            autostart.set_enabled(enabled)
        except OSError as error:
            log.warning("Could not change start at sign-in: %s", error)
            QMessageBox.warning(self, "HandGestures", f"Couldn't change the startup setting:\n{error}")

    def _reset(self):
        answer = QMessageBox.question(self, "Reset settings", "Put every setting back to its default?")
        if answer == QMessageBox.StandardButton.Yes:
            self._store.reset_to_defaults()


def _tab() -> tuple[QWidget, QVBoxLayout]:
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(8)
    return tab, layout


def _calibration_summary() -> str:
    profile = load_profile()
    if not profile.measured_at:
        return "Not calibrated yet: calibrating tunes the gestures to your hand, camera and light."
    when = profile.measured_at.replace("T", " at ")[:-3]
    return f"Last calibrated {when}."
