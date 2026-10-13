"""Moving the cursor and clicking for the pointing hand, smoothly, on a thread of its own."""
import logging
import queue
import threading
import time
from typing import Protocol

import pywintypes
import win32api
import win32con

from . import windows_input
from .config import Config
from .cursor_motion import CursorMapper

log = logging.getLogger(__name__)

# How often the driver moves the cursor along its glide: faster than any common screen refreshes.
TICK_S = 0.004
# The cursor glides to each new target over one camera frame interval, measured, within these limits.
MIN_GLIDE_S = 0.01
MAX_GLIDE_S = 0.07
GLIDE_SMOOTHING = 0.2  # weight of the newest frame interval in the running average
# The cursor moved more than this many pixels from where the driver put it: the mouse moved it.
MOUSE_MOVE_THRESHOLD = 1
CURSOR_ERRORS = (OSError, pywintypes.error)  # e.g. on the lock screen and UAC prompts


class Cursor(Protocol):
    def position(self) -> tuple[int, int]: ...
    def move(self, position: tuple[int, int]) -> None: ...
    def click(self) -> None: ...
    def screen_width(self) -> int: ...
    def bounds(self) -> tuple[int, int, int, int]: ...


class Win32Cursor:
    """The real cursor, in physical pixels (the app is DPI aware), across all monitors."""

    def position(self) -> tuple[int, int]:
        return win32api.GetCursorPos()

    def move(self, position: tuple[int, int]):
        win32api.SetCursorPos(position)

    def click(self):
        windows_input.left_click()

    def screen_width(self) -> int:
        """The main monitor's width: what pointer_speed is relative to."""
        return win32api.GetSystemMetrics(win32con.SM_CXSCREEN)

    def bounds(self) -> tuple[int, int, int, int]:
        """(left, top, right, bottom) of the rectangle around all monitors."""
        left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        return left, top, left + width, top + height


class PointerDriver:
    """Moves the cursor many times per camera frame, so it glides instead of jumping at camera rate.

    The camera thread sets where the cursor should go; the cursor travels there at an even speed
    over one camera frame interval, arriving about when the next target comes in. Clicks are
    queued in order with the moves. If the mouse moves the cursor, the driver lets go and reports
    it through take_interrupted(), so the hand can carry on from the cursor's new position.
    """

    def __init__(self, cursor: Cursor, start_thread: bool = True):
        self._cursor = cursor
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._clicks: queue.SimpleQueue[tuple[int, int] | None] = queue.SimpleQueue()
        self._closed = False
        self._target: tuple[float, float] | None = None
        self._glide_from = (0.0, 0.0)
        self._glide_start = 0.0
        self._glide_s = MIN_GLIDE_S
        self._last_set: tuple[int, int] | None = None  # where the driver last put the cursor
        self._interrupted = False
        self._thread = threading.Thread(target=self._run, name="pointer", daemon=True)
        if start_thread:
            self._thread.start()

    def move_to(self, target: tuple[float, float], glide_s: float):
        """Glide from wherever the cursor is heading now to `target`, over glide_s seconds."""
        with self._lock:
            now = time.monotonic()
            self._glide_from = self._position_at(now) or target
            self._target = target
            self._glide_start = now
            self._glide_s = max(glide_s, 1e-3)
        self._wake.set()

    def release(self):
        """Stop moving the cursor."""
        with self._lock:
            self._target = None
            self._last_set = None

    def click(self, at: tuple[int, int] | None):
        """Click at `at` (snapping the cursor there first), or wherever the cursor is if None."""
        self._clicks.put(at)
        self._wake.set()

    def take_interrupted(self) -> bool:
        """Has the mouse moved the cursor since the last call?"""
        with self._lock:
            interrupted, self._interrupted = self._interrupted, False
            return interrupted

    def close(self):
        self._closed = True
        self._wake.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1)

    def _run(self):
        while not self._closed:
            self._do_clicks()
            if self.step(time.monotonic()):
                time.sleep(TICK_S)  # Python 3.11+ sleeps with ~1 ms precision on Windows
            else:
                self._wake.wait(0.25)
                self._wake.clear()

    def step(self, now: float) -> bool:
        """Move the cursor along its glide. Return False when there's no target to move to."""
        with self._lock:
            position = self._position_at(now)
            last_set = self._last_set
        if position is None:
            return False
        try:
            if last_set is not None:
                actual = self._cursor.position()
                if max(abs(actual[0] - last_set[0]), abs(actual[1] - last_set[1])) > MOUSE_MOVE_THRESHOLD:
                    self._let_go()
                    return False
            pixel = (round(position[0]), round(position[1]))
            if pixel != last_set:
                self._cursor.move(pixel)
        except CURSOR_ERRORS:
            self._let_go()
            return False
        with self._lock:
            if self._target is not None:
                self._last_set = pixel
        return True

    def _position_at(self, now: float) -> tuple[float, float] | None:
        """Where the cursor should be at `now` on its glide; call with the lock held."""
        if self._target is None:
            return None
        progress = min(max((now - self._glide_start) / self._glide_s, 0.0), 1.0)
        (from_x, from_y), (to_x, to_y) = self._glide_from, self._target
        return from_x + (to_x - from_x) * progress, from_y + (to_y - from_y) * progress

    def _let_go(self):
        with self._lock:
            self._target = None
            self._last_set = None
            self._interrupted = True

    def _do_clicks(self):
        while True:
            try:
                at = self._clicks.get_nowait()
            except queue.Empty:
                return
            try:
                if at is not None:
                    self._cursor.move(at)
                    with self._lock:
                        if self._target is not None:
                            self._glide_from = self._target = at  # the glide is done: stay here
                            self._last_set = at
                self._cursor.click()
            except CURSOR_ERRORS as error:
                log.warning("Click failed: %s", error)


class PointerController:
    """Moves the cursor and clicks for the pointing hand: CursorMapper decides where the cursor
    goes, PointerDriver gets it there smoothly. With no cursor (dry run), clicks are only logged."""

    def __init__(self, config: Config, cursor: Cursor | None):
        self._cursor = cursor
        self._driver = PointerDriver(cursor) if cursor else None
        self._mapper = CursorMapper(config.pointer_speed, config.pointer_acceleration, 1920, (0, 0, 1920, 1080))
        self._active = False
        self._last_update_time: float | None = None
        self._glide_s = 1 / 30
        self._last_click_at: tuple[int, int] | None = None

    def configure(self, config: Config):
        self._mapper.speed = config.pointer_speed
        self._mapper.acceleration = config.pointer_acceleration

    def update(self, hand_position: tuple[float, float] | None, segment: int, scale: float, now: float):
        """Follow the hand at hand_position (frame widths; None when not pointing) for this frame."""
        if hand_position is None or self._driver is None:
            self.release()
            return
        interrupted = self._driver.take_interrupted()
        if (not self._active or interrupted) and not self._start():
            return
        self._track_frame_interval(now)
        target = self._mapper.update(hand_position, segment, scale, now)
        self._driver.move_to(target, self._glide_s)

    def release(self):
        if self._active:
            self._active = False
            self._mapper.stop()
            if self._driver:
                self._driver.release()
        self._last_update_time = None

    def click(self, aim_time: float | None):
        """Click where the cursor was at aim_time, when the user aimed (or where it is now)."""
        if self._driver is None:
            log.info("[dry-run] click")
            return
        target = self._mapper.rewind_to(aim_time) if self._active and aim_time is not None else None
        at = (round(target[0]), round(target[1])) if target else None
        self._driver.click(at)
        self._last_click_at = at

    def double_click(self):
        """The second click of a double click, exactly where the first landed."""
        if self._driver is None:
            log.info("[dry-run] click (second of a double click)")
            return
        if self._last_click_at and self._active:
            self._mapper.jump_to(self._last_click_at)
        self._driver.click(self._last_click_at)

    def close(self):
        self.release()
        if self._driver:
            self._driver.close()

    def _start(self) -> bool:
        """Start following from the cursor's current position; False if the cursor can't be read now."""
        try:
            self._mapper.screen_width = self._cursor.screen_width()
            self._mapper.bounds = self._cursor.bounds()
            self._mapper.start(self._cursor.position())
        except CURSOR_ERRORS:
            return False
        self._active = True
        return True

    def _track_frame_interval(self, now: float):
        if self._last_update_time is not None:
            interval = min(max(now - self._last_update_time, MIN_GLIDE_S), MAX_GLIDE_S)
            self._glide_s += GLIDE_SMOOTHING * (interval - self._glide_s)
        self._last_update_time = now
