"""Where the app keeps its settings, log and hand model."""
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # Installed build: the program folder isn't the place for user files, so settings
    # and the log live in %LOCALAPPDATA%, and the hand model ships inside the bundle.
    DATA_DIR = Path(os.environ["LOCALAPPDATA"]) / "HandGestures"
    MODEL_PATH = Path(sys._MEIPASS) / "models" / "hand_landmarker.task"
else:
    DATA_DIR = Path(__file__).resolve().parent.parent
    MODEL_PATH = DATA_DIR / "models" / "hand_landmarker.task"

CONFIG_PATH = DATA_DIR / "config.json"
LOG_PATH = DATA_DIR / "handgestures.log"
RECORDINGS_DIR = DATA_DIR / "recordings"
