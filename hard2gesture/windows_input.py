"""Synthesized keyboard and mouse input, through the Windows SendInput API.

Windows won't deliver it to apps running as administrator unless Hard2Gesture does too.
"""
import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800

# Virtual-key codes
VK_TAB = 0x09
VK_SHIFT = 0x10
VK_MENU = 0x12  # Alt
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_D = 0x44
VK_LWIN = 0x5B
VK_BROWSER_BACK = 0xA6
VK_BROWSER_FORWARD = 0xA7
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3

# Keys outside the original keyboard's main block, which Windows expects flagged as "extended".
EXTENDED_KEYS = {
    VK_LEFT, VK_RIGHT, VK_LWIN, VK_BROWSER_BACK, VK_BROWSER_FORWARD, VK_VOLUME_MUTE, VK_VOLUME_DOWN,
    VK_VOLUME_UP, VK_MEDIA_NEXT_TRACK, VK_MEDIA_PREV_TRACK, VK_MEDIA_PLAY_PAUSE,
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


_user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_user32.SendInput.restype = wintypes.UINT


def press_keys(*virtual_keys: int):
    """Press the keys in order, then release them in reverse: press_keys(VK_MENU, VK_TAB) is Alt+Tab."""
    _send(*(_key(key) for key in virtual_keys), *(_key(key, up=True) for key in reversed(virtual_keys)))


def key_down(virtual_key: int):
    _send(_key(virtual_key))


def key_up(virtual_key: int):
    _send(_key(virtual_key, up=True))


def scroll(wheel_delta: int):
    """Turn the mouse wheel by wheel_delta units (120 = one notch); positive scrolls up."""
    _send(_mouse(MOUSEEVENTF_WHEEL, wheel_delta & 0xFFFFFFFF))  # mouseData is unsigned


def left_click():
    _send(_mouse(MOUSEEVENTF_LEFTDOWN), _mouse(MOUSEEVENTF_LEFTUP))


def _key(virtual_key: int, up: bool = False) -> INPUT:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if virtual_key in EXTENDED_KEYS else 0)
    return INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(ki=KEYBDINPUT(wVk=virtual_key, dwFlags=flags)))


def _mouse(flags: int, data: int = 0) -> INPUT:
    return INPUT(type=INPUT_MOUSE, union=_INPUTUNION(mi=MOUSEINPUT(mouseData=data, dwFlags=flags)))


def _send(*inputs: INPUT):
    array = (INPUT * len(inputs))(*inputs)
    sent = _user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        # E.g. while the lock screen or a UAC prompt is showing.
        raise ctypes.WinError(ctypes.get_last_error())
