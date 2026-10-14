"""The webcam, read on a background thread so the newest frame is always ready."""
import logging
import threading
import time
from typing import NamedTuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Tried in order. Media Foundation can deliver twice DirectShow's frame rate from the
# same webcam (30 vs 15 fps); DirectShow is the fallback for cameras it can't open.
BACKENDS = (cv2.CAP_MSMF, cv2.CAP_DSHOW)
REQUESTED_FPS = 30
READ_RETRY_DELAY_S = 0.05  # wait before retrying after the camera fails to deliver a frame


class CameraUnavailableError(Exception):
    pass


class Frame(NamedTuple):
    image: np.ndarray  # BGR, mirrored so it moves like a mirror would
    capture_time: float  # time.monotonic() when it arrived


class Camera:
    """Keeps only the newest frame, so slow processing never falls behind on stale ones.

    Media Foundation queues several frames: reading them one by one while processing
    slower than the camera would mean working on frames 100+ ms old.
    Call close() (or use as a context manager) so the reader thread stops and the camera is released.
    """

    def __init__(self, index: int, width: int, height: int):
        self.index = index
        self._capture = _open_capture(index)
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._capture.set(cv2.CAP_PROP_FPS, REQUESTED_FPS)
        log.info("Camera %d: %dx%d at %.0f fps (%s)", index,
                 self._capture.get(cv2.CAP_PROP_FRAME_WIDTH), self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT),
                 self._capture.get(cv2.CAP_PROP_FPS), self._capture.getBackendName())

        self._frame_arrived = threading.Condition()
        self._newest_frame: Frame | None = None
        self._newest_frame_is_unread = False
        self._closed = False
        self._reader = threading.Thread(target=self._read_continuously, name="camera-reader", daemon=True)
        self._reader.start()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def close(self):
        with self._frame_arrived:
            if self._closed:
                return
            self._closed = True
            self._frame_arrived.notify_all()
        self._reader.join(timeout=1)
        self._capture.release()

    def latest_frame(self, timeout_s: float = 1.0) -> Frame | None:
        """Wait for a frame newer than the last one returned. Return None on timeout."""
        with self._frame_arrived:
            self._frame_arrived.wait_for(lambda: self._newest_frame_is_unread or self._closed, timeout_s)
            if not self._newest_frame_is_unread:
                return None
            self._newest_frame_is_unread = False
            return self._newest_frame

    def _read_continuously(self):
        while not self._closed:
            frame_read, image = self._capture.read()
            if not frame_read:
                time.sleep(READ_RETRY_DELAY_S)
                continue
            capture_time = time.monotonic()
            mirrored_image = cv2.flip(image, 1)
            with self._frame_arrived:
                self._newest_frame = Frame(mirrored_image, capture_time)
                self._newest_frame_is_unread = True
                self._frame_arrived.notify()


def _open_capture(index: int) -> cv2.VideoCapture:
    for backend in BACKENDS:
        capture = cv2.VideoCapture(index, backend)
        if capture.isOpened():
            return capture
        capture.release()
    raise CameraUnavailableError(f"Camera {index + 1} isn't available")


def camera_names() -> list[str]:
    """The webcams' names, in the order of their indexes; empty if they can't be listed."""
    try:
        from pygrabber.dshow_graph import FilterGraph  # lists DirectShow devices, which OpenCV numbers the same way

        return list(FilterGraph().get_input_devices())
    except Exception as error:  # COM can fail in many ways; the names are only a nicety
        log.warning("Could not list cameras: %s", error)
        return []
