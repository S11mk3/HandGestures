"""The system tray icon: shows the status; clicking it pauses, and its menu reaches everything else."""
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..tracking_loop import Status, StatusKind
from .icons import IconState, status_icon

ICON_STATES = {
    StatusKind.STARTING: IconState.CALIBRATING,
    StatusKind.CALIBRATING: IconState.CALIBRATING,
    StatusKind.RUNNING: IconState.ACTIVE,
    StatusKind.PROBLEM: IconState.PROBLEM,
}


class Tray(QObject):
    pause_toggled = Signal()
    preview_toggled = Signal(bool)
    recalibrate_requested = Signal()
    settings_requested = Signal()
    guide_requested = Signal()
    data_folder_requested = Signal()
    about_requested = Signal()
    quit_requested = Signal()

    def __init__(self):
        super().__init__()
        self._icons = {state: status_icon(state) for state in IconState}
        self._icon = QSystemTrayIcon(self._icons[IconState.CALIBRATING])
        self._icon.activated.connect(self._on_activated)

        self._menu = QMenu()
        self._pause_action = self._add_action("Pause", self.pause_toggled)
        self._preview_action = QAction("Show camera preview", self._menu, checkable=True)
        self._preview_action.toggled.connect(self.preview_toggled)
        self._menu.addAction(self._preview_action)
        self._add_action("Recalibrate", self.recalibrate_requested)
        self._menu.addSeparator()
        self._add_action("Settings…", self.settings_requested)
        self._add_action("Gesture guide…", self.guide_requested)
        self._add_action("Open settings and log folder", self.data_folder_requested)
        self._add_action("About Hard2Gesture", self.about_requested)
        self._menu.addSeparator()
        self._add_action("Quit", self.quit_requested)
        self._icon.setContextMenu(self._menu)

    def _add_action(self, text: str, signal) -> QAction:
        # Connected signal to signal: QMenu.addAction(text, signal) tries to call the signal, which
        # PySide6 refuses ("native Qt signal instance ... is not callable"), so the item did nothing.
        action = self._menu.addAction(text)
        action.triggered.connect(signal)
        return action

    def show(self):
        self._icon.show()

    def hide(self):
        self._icon.hide()

    def update(self, status: Status, paused: bool, preview_visible: bool):
        state = IconState.PAUSED if paused and status.kind is StatusKind.RUNNING else ICON_STATES[status.kind]
        self._icon.setIcon(self._icons[state])
        self._icon.setToolTip(f"Hard2Gesture: {'paused' if paused else status.message}"[:127])
        self._pause_action.setText("Resume" if paused else "Pause")
        self._preview_action.blockSignals(True)
        self._preview_action.setChecked(preview_visible)
        self._preview_action.blockSignals(False)

    def notify(self, message: str, warning: bool = False):
        icon = QSystemTrayIcon.MessageIcon.Warning if warning else QSystemTrayIcon.MessageIcon.Information
        self._icon.showMessage("Hard2Gesture", message, icon, 8000)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # a left click
            self.pause_toggled.emit()
