"""Performs the actions gestures are bound to (see bindings.py), plus scrolling."""
import logging
import os
from collections.abc import Callable

import win32con
import win32gui
import win32process

from . import windows_input as keys
from .bindings import ACTIONS

log = logging.getLogger(__name__)

# The desktop and the taskbar: never minimize these.
SHELL_WINDOW_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


class ActionRunner:
    """Runs actions by id. In dry-run mode it only logs them, for trying out gestures safely."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        windows = WindowControl()
        self._actions: dict[str, Callable[[], None]] = {
            "none": lambda: None,
            "next_window": lambda: keys.press_keys(keys.VK_MENU, keys.VK_TAB),
            "previous_window": lambda: keys.press_keys(keys.VK_MENU, keys.VK_SHIFT, keys.VK_TAB),
            "minimize": windows.minimize_active_window,
            "restore_minimized": windows.restore_last_minimized_window,
            "maximize": windows.maximize_active_window,
            "restore_down": windows.restore_down_active_window,
            "show_desktop": lambda: keys.press_keys(keys.VK_LWIN, keys.VK_D),
            "task_view": lambda: keys.press_keys(keys.VK_LWIN, keys.VK_TAB),
            # The media keys: YouTube, Spotify, VLC, etc. all respond to them.
            "play_pause": lambda: keys.press_keys(keys.VK_MEDIA_PLAY_PAUSE),
            "next_track": lambda: keys.press_keys(keys.VK_MEDIA_NEXT_TRACK),
            "previous_track": lambda: keys.press_keys(keys.VK_MEDIA_PREV_TRACK),
            "mute": lambda: keys.press_keys(keys.VK_VOLUME_MUTE),
            "volume_up": lambda: keys.press_keys(keys.VK_VOLUME_UP),
            "volume_down": lambda: keys.press_keys(keys.VK_VOLUME_DOWN),
            "browser_back": lambda: keys.press_keys(keys.VK_BROWSER_BACK),
            "browser_forward": lambda: keys.press_keys(keys.VK_BROWSER_FORWARD),
        }
        missing = ACTIONS.keys() - self._actions.keys()
        assert not missing, f"Actions without an implementation: {missing}"

    def run(self, action_id: str):
        if action_id == "none":
            return
        if self.dry_run:
            log.info("[dry-run] %s", ACTIONS[action_id].name)
            return
        self._actions[action_id]()

    def scroll(self, steps: int, wheel_units_per_step: int):
        if self.dry_run:
            log.info("[dry-run] scroll %+d", steps)
            return
        keys.scroll(steps * wheel_units_per_step)


class WindowControl:
    """Minimizes, maximizes and restores the active window, remembering which windows it minimized."""

    def __init__(self):
        self._minimized_windows: list[int] = []  # most recent last

    def minimize_active_window(self):
        window = _active_app_window()
        if window is None:
            return
        win32gui.ShowWindow(window, win32con.SW_MINIMIZE)
        self._minimized_windows.append(window)
        log.info("Minimized %r", win32gui.GetWindowText(window))

    def restore_last_minimized_window(self):
        # Skip windows that have since been closed or restored some other way.
        while self._minimized_windows:
            window = self._minimized_windows.pop()
            if win32gui.IsWindow(window) and win32gui.IsIconic(window):
                win32gui.ShowWindow(window, win32con.SW_RESTORE)
                _bring_to_front(window)
                log.info("Restored %r", win32gui.GetWindowText(window))
                return
        log.info("Nothing to restore")

    def maximize_active_window(self):
        window = _active_app_window()
        if window is None or not _can_maximize(window) or _is_maximized(window):
            return
        win32gui.ShowWindow(window, win32con.SW_MAXIMIZE)
        log.info("Maximized %r", win32gui.GetWindowText(window))

    def restore_down_active_window(self):
        window = _active_app_window()
        if window is None or not _is_maximized(window):
            return
        win32gui.ShowWindow(window, win32con.SW_RESTORE)
        log.info("Restored down %r", win32gui.GetWindowText(window))


def _active_app_window() -> int | None:
    """The foreground window, unless it's hidden, the desktop or taskbar, or one of ours."""
    window = win32gui.GetForegroundWindow()
    if not window or not win32gui.IsWindowVisible(window):
        return None
    if win32gui.GetClassName(window) in SHELL_WINDOW_CLASSES:
        return None
    _, process_id = win32process.GetWindowThreadProcessId(window)
    if process_id == os.getpid():
        return None
    return window


def _can_maximize(window: int) -> bool:
    return bool(win32gui.GetWindowLong(window, win32con.GWL_STYLE) & win32con.WS_MAXIMIZEBOX)


def _is_maximized(window: int) -> bool:
    _, show_state, *_ = win32gui.GetWindowPlacement(window)
    return show_state == win32con.SW_SHOWMAXIMIZED


def _bring_to_front(window: int):
    try:
        win32gui.SetForegroundWindow(window)
        return
    except win32gui.error:
        pass
    # Windows refuses focus changes from background processes unless they just
    # sent input; holding Alt during the call satisfies that rule.
    keys.key_down(keys.VK_MENU)
    try:
        win32gui.SetForegroundWindow(window)
    except win32gui.error as error:
        log.warning("Could not focus restored window: %s", error)
    finally:
        keys.key_up(keys.VK_MENU)
