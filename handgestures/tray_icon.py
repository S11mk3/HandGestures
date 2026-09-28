"""The system tray icon: shows the status, and its menu pauses, toggles the preview and quits."""
import pystray
from PIL import Image, ImageDraw

from .app_state import AppState

ACTIVE_COLOR = (46, 160, 67)  # green
PAUSED_COLOR = (140, 140, 140)  # gray
ICON_FILE_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)]


def draw_icon(background_color: tuple[int, int, int]) -> Image.Image:
    """A white open hand on a colored circle, 64x64 px."""
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    white = (255, 255, 255)
    draw.ellipse((2, 2, 62, 62), fill=background_color)
    draw.rounded_rectangle((20, 30, 44, 52), radius=6, fill=white)  # palm
    for finger_left in (20, 26, 32, 38):
        draw.rounded_rectangle((finger_left, 12, finger_left + 5, 34), radius=2, fill=white)
    draw.rounded_rectangle((42, 28, 50, 34), radius=2, fill=white)  # thumb
    return image


def save_icon_file(path: str):
    """Save the app icon as a multi-size .ico file, for the installer and the .exe."""
    draw_icon(ACTIVE_COLOR).save(path, sizes=ICON_FILE_SIZES)


def create_tray_icon(state: AppState) -> pystray.Icon:
    """Build the tray icon; icon.run() then shows it and blocks until Quit is chosen."""
    active_image = draw_icon(ACTIVE_COLOR)
    paused_image = draw_icon(PAUSED_COLOR)

    def current_image():
        return paused_image if state.paused else active_image

    def tooltip():
        return f"HandGestures - {'paused' if state.paused else state.status}"

    def toggle_pause():
        state.paused = not state.paused
        state.notify_changed()

    def toggle_preview():
        state.show_preview = not state.show_preview
        state.notify_changed()

    def quit_app(icon):
        icon.stop()

    menu = pystray.Menu(
        # The default item also runs when the icon itself is clicked.
        pystray.MenuItem(lambda item: "Resume" if state.paused else "Pause", toggle_pause, default=True),
        pystray.MenuItem("Show preview", toggle_preview, checked=lambda item: state.show_preview),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("HandGestures", current_image(), tooltip(), menu)

    def refresh():
        icon.icon = current_image()
        icon.title = tooltip()
        icon.update_menu()

    state.on_change = refresh
    return icon
