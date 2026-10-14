"""The tray menu: every item reaches the app."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # nothing is shown on screen

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hard2gesture.ui.tray import Tray  # noqa: E402

# Menu item -> the Tray signal it must emit, in menu order.
MENU_SIGNALS = {
    "Pause": "pause_toggled",
    "Recalibrate": "recalibrate_requested",
    "Settings…": "settings_requested",
    "Gesture guide…": "guide_requested",
    "Open settings and log folder": "data_folder_requested",
    "About Hard2Gesture": "about_requested",
    "Quit": "quit_requested",
}


@pytest.fixture(scope="module")
def tray():
    app = QApplication.instance() or QApplication([])
    yield Tray()
    app.processEvents()


def test_every_menu_item_emits_its_signal(tray):
    fired = []
    for signal in MENU_SIGNALS.values():
        getattr(tray, signal).connect(lambda name=signal: fired.append(name))
    items = [action for action in tray._menu.actions() if action.text() and not action.isCheckable()]
    assert [action.text() for action in items] == list(MENU_SIGNALS)
    for action in items:
        action.trigger()
    assert fired == list(MENU_SIGNALS.values())
