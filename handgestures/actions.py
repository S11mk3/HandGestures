"""What each gesture does in Windows."""
import logging
from typing import Protocol

import pyautogui
import win32api
import win32con
import win32gui

from .config import Config
from .gestures import Gesture, GestureEvent

log = logging.getLogger(__name__)

# We never move the mouse, so the corner fail-safe would only cause spurious errors,
# and the default 0.1 s pause after every call would stall the camera loop.
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

# The desktop and the taskbar: never minimize these.
SHELL_WINDOW_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}

ACTION_NAMES = {
    Gesture.SWIPE_DOWN: "Minimize",
    Gesture.SWIPE_UP: "Restore minimized",
    Gesture.SWIPE_LEFT: "Alt+Tab",
    Gesture.SWIPE_RIGHT: "Alt+Shift+Tab",
    Gesture.FIST_HOLD: "Play/Pause",
    Gesture.SCROLL: "Scroll",
    Gesture.HANDS_APART: "Maximize",
    Gesture.HANDS_TOGETHER: "Restore down",
}


class Actions(Protocol):
    def minimize_active_window(self) -> None: ...
    def restore_last_minimized_window(self) -> None: ...
    def maximize_active_window(self) -> None: ...
    def restore_down_active_window(self) -> None: ...
    def switch_to_next_window(self) -> None: ...
    def switch_to_previous_window(self) -> None: ...
    def toggle_media_playback(self) -> None: ...
    def scroll(self, steps: int) -> None: ...


def perform(actions: Actions, event: GestureEvent) -> None:
    match event.gesture:
        case Gesture.SWIPE_DOWN:
            actions.minimize_active_window()
        case Gesture.SWIPE_UP:
            actions.restore_last_minimized_window()
        case Gesture.SWIPE_LEFT:
            actions.switch_to_next_window()
        case Gesture.SWIPE_RIGHT:
            actions.switch_to_previous_window()
        case Gesture.FIST_HOLD:
            actions.toggle_media_playback()
        case Gesture.SCROLL:
            actions.scroll(event.scroll_steps)
        case Gesture.HANDS_APART:
            actions.maximize_active_window()
        case Gesture.HANDS_TOGETHER:
            actions.restore_down_active_window()


def describe(event: GestureEvent) -> str:
    """Short name of the event's action, e.g. "Minimize" or "Scroll +2"."""
    name = ACTION_NAMES[event.gesture]
    if event.gesture is Gesture.SCROLL:
        return f"{name} {event.scroll_steps:+d}"
    return name


class WindowsActions:
    """Performs the actions for real."""

    def __init__(self, config: Config, ignored_window_titles: set[str]):
        self._scroll_amount = config.scroll_amount
        self._ignored_window_titles = ignored_window_titles
        self._minimized_windows: list[int] = []  # most recent last

    def minimize_active_window(self):
        window = self._active_app_window()
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
        window = self._active_app_window()
        if window is None or not _can_maximize(window) or _is_maximized(window):
            return
        win32gui.ShowWindow(window, win32con.SW_MAXIMIZE)
        log.info("Maximized %r", win32gui.GetWindowText(window))

    def restore_down_active_window(self):
        window = self._active_app_window()
        if window is None or not _is_maximized(window):
            return
        win32gui.ShowWindow(window, win32con.SW_RESTORE)
        log.info("Restored down %r", win32gui.GetWindowText(window))

    def switch_to_next_window(self):
        pyautogui.hotkey("alt", "tab")

    def switch_to_previous_window(self):
        pyautogui.hotkey("alt", "shift", "tab")

    def toggle_media_playback(self):
        pyautogui.press("playpause")  # the media key: YouTube, Spotify, VLC, etc.

    def scroll(self, steps: int):
        pyautogui.scroll(steps * self._scroll_amount)

    def _active_app_window(self) -> int | None:
        """The foreground window, unless it's hidden, the desktop or taskbar, or one of ours."""
        window = win32gui.GetForegroundWindow()
        if not window or not win32gui.IsWindowVisible(window):
            return None
        if win32gui.GetClassName(window) in SHELL_WINDOW_CLASSES:
            return None
        if win32gui.GetWindowText(window) in self._ignored_window_titles:
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
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    try:
        win32gui.SetForegroundWindow(window)
    except win32gui.error as error:
        log.warning("Could not focus restored window: %s", error)
    finally:
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)


class DryRunActions:
    """Only logs the actions, for testing and tuning gestures."""

    def minimize_active_window(self):
        log.info("[dry-run] minimize active window")

    def restore_last_minimized_window(self):
        log.info("[dry-run] restore last minimized window")

    def maximize_active_window(self):
        log.info("[dry-run] maximize active window")

    def restore_down_active_window(self):
        log.info("[dry-run] restore down active window")

    def switch_to_next_window(self):
        log.info("[dry-run] alt+tab")

    def switch_to_previous_window(self):
        log.info("[dry-run] alt+shift+tab")

    def toggle_media_playback(self):
        log.info("[dry-run] media play/pause")

    def scroll(self, steps: int):
        log.info("[dry-run] scroll %+d", steps)
