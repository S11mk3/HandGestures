"""Start HandGestures: a tray icon plus a camera thread that turns hand gestures into actions."""
import argparse
import logging
import sys

import win32api
import win32event
import winerror

from handgestures.actions import DryRunActions, WindowsActions
from handgestures.app_state import AppState
from handgestures.camera_loop import CameraLoop
from handgestures.config import load_config
from handgestures.paths import DATA_DIR, LOG_PATH
from handgestures.preview_window import PREVIEW_WINDOW_TITLE
from handgestures.recorder import Recorder, new_recording_path
from handgestures.tray_icon import create_tray_icon

# The installer checks for this mutex too, to ask the user to quit the app before updating it.
SINGLE_INSTANCE_MUTEX_NAME = "HandGesturesRunning"

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Control Windows with hand gestures.")
    parser.add_argument("--dry-run", action="store_true", help="log gestures without performing actions")
    parser.add_argument("--no-preview", action="store_true", help="start with the camera preview hidden")
    parser.add_argument("--record", action="store_true", help="record hand movements (no camera image) for tuning")
    return parser.parse_args()


def setup_logging():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stderr:  # None in the windowed (installed) build
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def acquire_single_instance_lock():
    """Return a handle to keep open until exit, or None if HandGestures is already running.

    A second copy would fight over the camera and perform every action twice.
    """
    mutex = win32event.CreateMutex(None, False, SINGLE_INSTANCE_MUTEX_NAME)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        return None
    return mutex


def main():
    args = parse_args()
    setup_logging()
    instance_lock = acquire_single_instance_lock()  # released when the process exits
    if instance_lock is None:
        log.info("HandGestures is already running; exiting")
        return

    config = load_config()
    if args.dry_run:
        actions = DryRunActions()
    else:
        actions = WindowsActions(config, ignored_window_titles={PREVIEW_WINDOW_TITLE})

    recorder = Recorder(new_recording_path("everyday"), config) if args.record else None
    if recorder:
        log.info("Recording hand movements to %s", recorder.path)

    state = AppState(show_preview=not args.no_preview)
    tray_icon = create_tray_icon(state)
    camera_loop = CameraLoop(state, config, actions, recorder)
    camera_loop.start()
    try:
        tray_icon.run()  # blocks until Quit
    finally:
        camera_loop.stop()
        if recorder:
            recorder.close()


if __name__ == "__main__":
    main()
