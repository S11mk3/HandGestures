"""Switches the UI (main thread) flips and the camera thread reads every frame."""
import threading
from dataclasses import dataclass, field


@dataclass
class AppState:
    paused: bool = False
    # Some window shows the camera image, so the camera thread sends it frames.
    frames_wanted: bool = False
    # The gesture guide is open: recognize gestures, but don't perform their actions.
    practice_mode: bool = False
    calibration_requested: threading.Event = field(default_factory=threading.Event)
    calibration_skip_requested: threading.Event = field(default_factory=threading.Event)
