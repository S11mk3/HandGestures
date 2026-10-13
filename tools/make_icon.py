"""Writes assets/icon.ico (for the .exe and the installer) and assets/icon.png from the app's own icon drawing.

Run after changing handgestures/ui/icons.py:  .venv/Scripts/python tools/make_icon.py
"""
import os
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from handgestures.ui.icons import ICON_SIZES, IconState, draw_icon  # noqa: E402


def render(size: int) -> Image.Image:
    """The icon drawn at this exact size: sharper than shrinking the biggest one."""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    draw_icon(IconState.ACTIVE.value, size).save(buffer, "PNG")
    return Image.open(BytesIO(bytes(buffer.data()))).convert("RGBA")


def main():
    QGuiApplication(sys.argv)
    images = [render(size) for size in ICON_SIZES]
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    largest = images[-1]
    largest.save(assets / "icon.ico", sizes=[(size, size) for size in ICON_SIZES], append_images=images[:-1])
    largest.save(assets / "icon.png")
    print(f"Wrote {assets / 'icon.ico'} and {assets / 'icon.png'}")


if __name__ == "__main__":
    main()
