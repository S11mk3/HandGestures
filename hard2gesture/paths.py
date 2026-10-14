"""Where the app keeps its settings, calibration, log and hand model."""
import os
import sys
from pathlib import Path

IS_FROZEN = getattr(sys, "frozen", False)

if IS_FROZEN:
    # Installed build: the program folder isn't the place for user files, so settings
    # and the log live in %LOCALAPPDATA%, and the hand model ships inside the bundle.
    APP_DIR = Path(sys.executable).parent
    DATA_DIR = Path(os.environ["LOCALAPPDATA"]) / "Hard2Gesture"
    MODEL_PATH = Path(sys._MEIPASS) / "models" / "hand_landmarker.task"
else:
    APP_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = APP_DIR
    MODEL_PATH = DATA_DIR / "models" / "hand_landmarker.task"

CONFIG_PATH = DATA_DIR / "config.json"
CALIBRATION_PATH = DATA_DIR / "calibration.json"
WINDOW_STATE_PATH = DATA_DIR / "window_state.ini"  # where the windows were last placed
LOG_PATH = DATA_DIR / "hard2gesture.log"
