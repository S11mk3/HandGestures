"""Logging to a size-limited file (and the console, when there is one), including uncaught exceptions."""
import logging
import logging.handlers
import platform
import sys
import threading

from . import __version__
from .paths import DATA_DIR, LOG_PATH

MAX_LOG_BYTES = 1_000_000
LOG_BACKUP_COUNT = 2  # handgestures.log.1 and .2

log = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8")]
    if sys.stderr:  # None in the windowed (installed) build
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    sys.excepthook = _log_uncaught_exception
    threading.excepthook = _log_uncaught_thread_exception
    log.info("HandGestures %s, Windows %s, Python %s", __version__, platform.version(), platform.python_version())


def _log_uncaught_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    log.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


def _log_uncaught_thread_exception(args: threading.ExceptHookArgs):
    thread_name = args.thread.name if args.thread else "?"
    log.critical("Uncaught exception in thread %s", thread_name,
                 exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
