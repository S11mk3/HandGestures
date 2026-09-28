"""State shared by the tray icon (main thread) and the camera loop (background thread)."""
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class AppState:
    paused: bool = False
    show_preview: bool = True
    status: str = "Starting..."
    # Called after every change; the tray icon sets it to refresh itself.
    on_change: Callable[[], None] = field(default=lambda: None, repr=False)

    def notify_changed(self):
        self.on_change()

    def set_status(self, status: str):
        self.status = status
        self.notify_changed()
