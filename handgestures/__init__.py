"""Control Windows with hand gestures seen by the webcam."""
import os

# Opening a camera through Media Foundation takes ~6 s with its hardware transforms on
# and under 1 s with them off. OpenCV reads this once, so it must be set before cv2 is imported.
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

__version__ = "1.2.0"
