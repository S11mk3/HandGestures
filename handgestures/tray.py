import pystray
from PIL import Image, ImageDraw

from .worker import AppState

ACTIVE_COLOR = (46, 160, 67)
PAUSED_COLOR = (140, 140, 140)


def _icon_image(color) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=color)
    # A simple open-hand glyph: palm plus four fingers and a thumb.
    white = (255, 255, 255)
    d.rounded_rectangle((20, 30, 44, 52), radius=6, fill=white)
    for x in (20, 26, 32, 38):
        d.rounded_rectangle((x, 12, x + 5, 34), radius=2, fill=white)
    d.rounded_rectangle((42, 28, 50, 34), radius=2, fill=white)
    return img


def build_icon(state: AppState) -> pystray.Icon:
    images = {False: _icon_image(ACTIVE_COLOR), True: _icon_image(PAUSED_COLOR)}

    def title():
        mode = "paused" if state.paused else state.status
        return f"HandGestures - {mode}"

    def toggle_pause(icon, item):
        state.paused = not state.paused
        state.changed()

    def toggle_preview(icon, item):
        state.show_preview = not state.show_preview
        state.changed()

    def quit_app(icon, item):
        state.running = False
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: "Resume" if state.paused else "Pause", toggle_pause, default=True),
        pystray.MenuItem("Show preview", toggle_preview, checked=lambda item: state.show_preview),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("HandGestures", images[state.paused], title(), menu)

    def refresh():
        icon.icon = images[state.paused]
        icon.title = title()
        icon.update_menu()

    state.on_change = refresh
    return icon
