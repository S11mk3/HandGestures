"""Starting HandGestures when the user signs in to Windows, through the registry's Run key."""
import contextlib
import logging
import sys
import winreg
from pathlib import Path

from .paths import IS_FROZEN

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "HandGestures"  # must match the [Registry] entry in installer\HandGestures.iss


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            with contextlib.suppress(FileNotFoundError):  # already off
                winreg.DeleteValue(key, VALUE_NAME)
    log.info("Start at sign-in %s", "on" if enabled else "off")


def startup_command() -> str:
    """At sign-in, start quietly: no camera preview (it can be shown from the tray menu)."""
    if IS_FROZEN:
        return f'"{sys.executable}" --no-preview'
    # Running from source: pythonw.exe, which opens no console window.
    python = Path(sys.executable).with_name("pythonw.exe")
    main_script = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{python}" "{main_script}" --no-preview'
