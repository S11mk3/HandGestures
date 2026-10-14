"""What gestures do: the actions to choose from, and the action each gesture does by default.

Pointing, pinching and scrolling always do the same thing; they can only be switched off.
"""
from typing import NamedTuple

from .gestures import Gesture, GestureEvent


class ActionInfo(NamedTuple):
    name: str  # in Settings
    short_name: str  # on the camera preview, after a gesture


# Action id -> names, in the order Settings lists them. Ids are stored in config.json: never rename one.
ACTIONS = {
    "none": ActionInfo("Do nothing", "Nothing"),
    "next_window": ActionInfo("Switch to the next window (Alt+Tab)", "Alt+Tab"),
    "previous_window": ActionInfo("Switch to the previous window (Alt+Shift+Tab)", "Alt+Shift+Tab"),
    "minimize": ActionInfo("Minimize the window", "Minimize"),
    "restore_minimized": ActionInfo("Restore the last minimized window", "Restore minimized"),
    "maximize": ActionInfo("Maximize the window", "Maximize"),
    "restore_down": ActionInfo("Restore down the window", "Restore down"),
    "show_desktop": ActionInfo("Show the desktop (Win+D)", "Show desktop"),
    "task_view": ActionInfo("Task view (Win+Tab)", "Task view"),
    "play_pause": ActionInfo("Play / pause media", "Play/Pause"),
    "next_track": ActionInfo("Next track", "Next track"),
    "previous_track": ActionInfo("Previous track", "Previous track"),
    "mute": ActionInfo("Mute / unmute", "Mute"),
    "volume_up": ActionInfo("Volume up", "Volume up"),
    "volume_down": ActionInfo("Volume down", "Volume down"),
    "browser_back": ActionInfo("Go back (browser, File Explorer)", "Back"),
    "browser_forward": ActionInfo("Go forward (browser, File Explorer)", "Forward"),
}

# The gestures whose action the user picks, in the order Settings lists them, with their defaults.
DEFAULT_GESTURE_ACTIONS = {
    Gesture.SWIPE_LEFT.value: "next_window",
    Gesture.SWIPE_RIGHT.value: "previous_window",
    Gesture.SWIPE_DOWN.value: "minimize",
    Gesture.SWIPE_UP.value: "restore_minimized",
    Gesture.FIST_HOLD.value: "play_pause",
    Gesture.HANDS_APART.value: "maximize",
    Gesture.HANDS_TOGETHER.value: "restore_down",
}
BINDABLE_GESTURES = tuple(Gesture(gesture_id) for gesture_id in DEFAULT_GESTURE_ACTIONS)

FIXED_ACTION_NAMES = {
    Gesture.PINCH: "Click",
    Gesture.DOUBLE_PINCH: "Double click",
}


def action_for(gesture: Gesture, gesture_actions: dict[str, str]) -> str:
    """The id of the action a bindable gesture does."""
    return gesture_actions.get(gesture.value, DEFAULT_GESTURE_ACTIONS[gesture.value])


def describe(event: GestureEvent, gesture_actions: dict[str, str]) -> str:
    """Short name of what the event does, e.g. "Minimize" or "Scroll +2"."""
    if event.gesture is Gesture.SCROLL:
        return f"Scroll {event.scroll_steps:+d}"
    if event.gesture in FIXED_ACTION_NAMES:
        return FIXED_ACTION_NAMES[event.gesture]
    return ACTIONS[action_for(event.gesture, gesture_actions)].short_name
