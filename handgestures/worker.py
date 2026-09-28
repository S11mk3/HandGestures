import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import cv2
import win32api
import win32con
import win32gui

from .gestures import Event, GestureEngine
from .tracker import HandTracker

log = logging.getLogger(__name__)

PREVIEW_TITLE = "HandGestures preview"

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
]

EVENT_LABELS = {
    "SWIPE_DOWN": "Minimize",
    "SWIPE_UP": "Restore",
    "SWIPE_LEFT": "Alt+Tab",
    "SWIPE_RIGHT": "Alt+Shift+Tab",
    "PLAY_PAUSE": "Play/Pause",
}


@dataclass
class AppState:
    """Shared between the tray (main thread) and the camera worker thread."""
    paused: bool = False
    show_preview: bool = True
    running: bool = True
    status: str = "Starting..."
    on_change: Callable[[], None] = field(default=lambda: None, repr=False)

    def changed(self):
        self.on_change()


def dispatch(event: Event, actions, state: AppState):
    kind = event.kind
    if kind == "PLAY_PAUSE":
        actions.play_pause()
    elif kind == "SWIPE_DOWN":
        actions.minimize_foreground()
    elif kind == "SWIPE_UP":
        actions.restore_last()
    elif kind == "SWIPE_LEFT":
        actions.alt_tab()
    elif kind == "SWIPE_RIGHT":
        actions.alt_tab(reverse=True)
    elif kind == "SCROLL":
        actions.scroll(event.value)


def draw_preview(frame, lm, pose, last_label, paused):
    h, w = frame.shape[:2]
    s = w / 640  # sizes below were designed for a 640-wide frame
    font = max(0.7 * s, 0.45)  # below ~0.45 Hershey text stops being legible
    thick = 1 if font < 0.6 else 2
    line_h = int(font * 40)
    pad = max(int(10 * s), 6)
    if lm:
        pts = [(int(x * w), int(y * h)) for x, y, _ in lm]
        for a, b in HAND_CONNECTIONS:
            cv2.line(frame, pts[a], pts[b], (255, 255, 255), max(int(2 * s + 0.5), 1))
        for p in pts:
            cv2.circle(frame, p, max(int(4 * s + 0.5), 2), (0, 200, 0), -1)
    pose_text = pose.value if pose else "no hand"
    cv2.putText(frame, f"Pose: {pose_text}", (pad, line_h), cv2.FONT_HERSHEY_SIMPLEX, font, (0, 255, 255), thick)
    if last_label:
        cv2.putText(frame, f"Last: {last_label}", (pad, 2 * line_h), cv2.FONT_HERSHEY_SIMPLEX, font,
                    (0, 255, 255), thick)
    if paused:
        banner = int(line_h * 1.7)
        cv2.rectangle(frame, (0, h - banner), (w, h), (0, 0, 180), -1)
        cv2.putText(frame, "PAUSED - resume from tray", (pad, h - (banner - line_h // 2) // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, font, (255, 255, 255), thick)


def pin_preview_window(previous_foreground: int, image_size: tuple[int, int]):
    """Keep the preview above other windows, in the bottom-right corner, out of the way.

    It becomes a tool window that can't be activated: that keeps it out of the
    Alt+Tab list (otherwise Alt+Tab would just switch to the preview) and stops
    clicks on it from stealing focus. OpenCV activates the window when it creates
    it, so focus is also handed back to whatever had it before.
    """
    hwnd = win32gui.FindWindow(None, PREVIEW_TITLE)
    if not hwnd:
        return
    ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    ex = (ex | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE) & ~win32con.WS_EX_APPWINDOW
    # The shell only re-reads Alt+Tab/taskbar membership when a window is shown.
    win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex)
    win32gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER
                          | win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED)

    # A tool window's title bar is thinner; size the frame so the image still fits exactly.
    left, top, win_right, win_bottom = win32gui.GetWindowRect(hwnd)
    _, _, client_w, client_h = win32gui.GetClientRect(hwnd)
    width = image_size[0] + (win_right - left) - client_w
    height = image_size[1] + (win_bottom - top) - client_h

    monitor = win32api.MonitorFromPoint((0, 0), win32con.MONITOR_DEFAULTTOPRIMARY)
    _, _, right, bottom = win32api.GetMonitorInfo(monitor)["Work"]  # excludes the taskbar
    margin = 20  # OpenCV snaps its windows flush to a screen edge when within ~15 px of it
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST,
                          right - width - margin, bottom - height - margin, width, height,
                          win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW)
    if (win32gui.GetForegroundWindow() == hwnd and previous_foreground
            and previous_foreground != hwnd and win32gui.IsWindow(previous_foreground)):
        win32gui.SetForegroundWindow(previous_foreground)


def run(state: AppState, cfg: dict, actions):
    cap = cv2.VideoCapture(cfg["camera_index"], cv2.CAP_DSHOW)
    if not cap.isOpened():
        state.status = f"Camera {cfg['camera_index']} not available"
        log.error(state.status)
        state.changed()
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg["frame_width"])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg["frame_height"])

    tracker = None
    preview_open = False
    try:
        tracker = HandTracker(cfg)
        engine = GestureEngine(cfg)
        state.status = "Running"
        state.changed()
        log.info("Tracking started on camera %d", cfg["camera_index"])
        last_label, last_label_t = "", 0.0

        while state.running:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            frame = cv2.flip(frame, 1)
            lm = tracker.process(frame)
            now = time.monotonic()

            for event in engine.update(lm, now, state.paused):
                log.info("Gesture: %s%s", event.kind, f" {event.value:+d}" if event.kind == "SCROLL" else "")
                last_label = EVENT_LABELS.get(event.kind, f"Scroll {event.value:+d}")
                last_label_t = now
                try:
                    dispatch(event, actions, state)
                except Exception:
                    log.exception("Action for %s failed", event.kind)
            if now - last_label_t > 2.0:
                last_label = ""

            if state.show_preview:
                fh, fw = frame.shape[:2]
                pw = cfg["preview_width"]
                small = cv2.resize(frame, (pw, round(fh * pw / fw)), interpolation=cv2.INTER_AREA)
                draw_preview(small, lm, engine.pose, last_label, state.paused)
                creating = not preview_open
                if creating:
                    previous_foreground = win32gui.GetForegroundWindow()
                cv2.imshow(PREVIEW_TITLE, small)
                cv2.waitKey(1)
                if creating:
                    preview_open = True
                    try:
                        pin_preview_window(previous_foreground, (small.shape[1], small.shape[0]))
                    except win32gui.error as e:
                        log.warning("Could not pin the preview window: %s", e)
                if cv2.getWindowProperty(PREVIEW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                    state.show_preview = False  # user closed the window with its X button
                    preview_open = False
                    state.changed()
            elif preview_open:
                cv2.destroyWindow(PREVIEW_TITLE)
                cv2.waitKey(1)
                preview_open = False
    except Exception:
        log.exception("Camera worker crashed")
        state.status = "Error - see handgestures.log"
        state.changed()
    finally:
        cap.release()
        if tracker:
            tracker.close()
        cv2.destroyAllWindows()


def start(state: AppState, cfg: dict, actions) -> threading.Thread:
    thread = threading.Thread(target=run, args=(state, cfg, actions), name="camera", daemon=True)
    thread.start()
    return thread
