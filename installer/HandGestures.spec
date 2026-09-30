# PyInstaller spec for the standalone app in dist\HandGestures. Run installer\build.ps1
# rather than this directly: it downloads the hand model and makes the icon first.
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    # MediaPipe loads libmediapipe.dll with ctypes from importlib.resources.files("mediapipe.tasks.c"),
    # which import analysis can't see: collect both the DLL and that package explicitly.
    binaries=collect_dynamic_libs("mediapipe"),
    hiddenimports=["mediapipe.tasks.c"],
    # Shipping the model means the installed app works offline from the first run.
    datas=[(str(ROOT / "models" / "hand_landmarker.task"), "models")],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HandGestures",
    icon=str(ROOT / "build" / "icon.ico"),
    console=False,
    upx=False,  # UPX-packed executables are a common antivirus false positive
)
coll = COLLECT(exe, a.binaries, a.datas, name="HandGestures", upx=False)
