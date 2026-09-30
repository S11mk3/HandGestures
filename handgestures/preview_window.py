"""The small always-on-top window showing the camera image, the tracked hand and the last action."""
import logging
from dataclasses import dataclass

import cv2
import win32api
import win32con
import win32gui

from .hand_landmarks import HAND_CONNECTIONS, Landmarks

log = logging.getLogger(__name__)

PREVIEW_WINDOW_TITLE = "HandGestures preview"

# OpenCV snaps its windows flush to a screen edge when within ~15 px of it.
SCREEN_EDGE_MARGIN = 20

# OpenCV colors are BGR.
WHITE = (255, 255, 255)
GREEN = (0, 200, 0)
YELLOW = (0, 255, 255)
DARK_RED = (0, 0, 180)
FONT = cv2.FONT_HERSHEY_SIMPLEX


@dataclass(frozen=True)
class Overlay:
    """What to draw over the camera image."""
    hands: list[Landmarks]
    pose_label: str  # e.g. "fist" or "open palm + open palm"
    speed: str  # e.g. "24 fps, 45 ms"
    last_action: str  # empty when there's none to show
    paused: bool


class PreviewWindow:
    """Must be used from a single thread: OpenCV windows belong to the thread that made them."""

    def __init__(self, width: int):
        self._width = width
        self._is_open = False

    def show(self, frame, overlay: Overlay) -> bool:
        """Display the frame with the overlay. Return False if the user has closed the window."""
        frame_height, frame_width = frame.shape[:2]
        height = round(frame_height * self._width / frame_width)
        image = cv2.resize(frame, (self._width, height), interpolation=cv2.INTER_AREA)
        draw_overlay(image, overlay)

        is_opening = not self._is_open
        if is_opening:
            previous_foreground_window = win32gui.GetForegroundWindow()
        cv2.imshow(PREVIEW_WINDOW_TITLE, image)
        # Lets OpenCV draw and handle window events. waitKey(1) would do the same but
        # take ~15 ms, a full tick of the Windows timer.
        cv2.pollKey()
        if is_opening:
            self._is_open = True
            try:
                _pin_window(previous_foreground_window, (self._width, height))
            except win32gui.error as error:
                log.warning("Could not pin the preview window: %s", error)

        if cv2.getWindowProperty(PREVIEW_WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
            self._is_open = False  # closed with its X button
            return False
        return True

    def close(self):
        if self._is_open:
            cv2.destroyWindow(PREVIEW_WINDOW_TITLE)
            cv2.pollKey()
            self._is_open = False


def draw_overlay(image, overlay: Overlay):
    """Draw the hand skeleton and status text onto the image, in place."""
    height, width = image.shape[:2]
    scale = width / 640  # the sizes below were chosen for a 640 px wide image
    font_scale = max(0.7 * scale, 0.45)  # smaller Hershey text stops being legible
    text_thickness = 1 if font_scale < 0.6 else 2
    line_height = int(font_scale * 40)
    padding = max(int(10 * scale), 6)

    def draw_text(text: str, baseline_y: int, color=YELLOW):
        cv2.putText(image, text, (padding, baseline_y), FONT, font_scale, color, text_thickness)

    for hand in overlay.hands:
        points = [(int(x * width), int(y * height)) for x, y, _ in hand]
        for start, end in HAND_CONNECTIONS:
            cv2.line(image, points[start], points[end], WHITE, max(round(2 * scale), 1))
        for point in points:
            cv2.circle(image, point, max(round(4 * scale), 2), GREEN, cv2.FILLED)

    draw_text(f"Pose: {overlay.pose_label}", line_height)
    draw_text(overlay.speed, 2 * line_height)
    if overlay.last_action:
        draw_text(f"Last: {overlay.last_action}", 3 * line_height)
    if overlay.paused:
        banner_height = int(line_height * 1.7)
        cv2.rectangle(image, (0, height - banner_height), (width, height), DARK_RED, cv2.FILLED)
        draw_text("PAUSED - resume from tray", height - (banner_height - line_height // 2) // 2, WHITE)


def _pin_window(previous_foreground_window: int, image_size: tuple[int, int]):
    """Keep the preview above other windows, at the middle of the screen's left edge.

    OpenCV activates the window when it creates it, so focus is handed back to
    whatever had it before.
    """
    window = win32gui.FindWindow(None, PREVIEW_WINDOW_TITLE)
    if not window:
        return
    _make_tool_window(window)
    width, height = _window_size_for_image(window, image_size)
    x, y = _middle_left_of_screen(width, height)
    win32gui.SetWindowPos(window, win32con.HWND_TOPMOST, x, y, width, height,
                          win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW)

    focus_was_taken = win32gui.GetForegroundWindow() == window
    if focus_was_taken and previous_foreground_window and win32gui.IsWindow(previous_foreground_window):
        win32gui.SetForegroundWindow(previous_foreground_window)


def _make_tool_window(window: int):
    """Keep the window out of Alt+Tab (otherwise Alt+Tab would just switch to the
    preview) and the taskbar, and stop clicks on it from taking focus."""
    style = win32gui.GetWindowLong(window, win32con.GWL_EXSTYLE)
    style = (style | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE) & ~win32con.WS_EX_APPWINDOW
    # The shell only re-reads Alt+Tab and taskbar membership when a window is shown.
    win32gui.ShowWindow(window, win32con.SW_HIDE)
    win32gui.SetWindowLong(window, win32con.GWL_EXSTYLE, style)
    win32gui.SetWindowPos(window, 0, 0, 0, 0, 0,
                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER
                          | win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED)


def _window_size_for_image(window: int, image_size: tuple[int, int]) -> tuple[int, int]:
    """Outer window size whose inside fits the image exactly (a tool window's title bar is thinner)."""
    left, top, right, bottom = win32gui.GetWindowRect(window)
    _, _, inner_width, inner_height = win32gui.GetClientRect(window)
    image_width, image_height = image_size
    return (image_width + (right - left) - inner_width,
            image_height + (bottom - top) - inner_height)


def _middle_left_of_screen(width: int, height: int) -> tuple[int, int]:
    """Top-left corner that centers a window of this size vertically on the primary screen's left edge."""
    monitor = win32api.MonitorFromPoint((0, 0), win32con.MONITOR_DEFAULTTOPRIMARY)
    left, top, _, bottom = win32api.GetMonitorInfo(monitor)["Work"]  # the screen minus the taskbar
    return left + SCREEN_EDGE_MARGIN, top + (bottom - top - height) // 2
