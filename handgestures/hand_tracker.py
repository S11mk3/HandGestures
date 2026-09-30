"""Finds hands in camera frames with MediaPipe's hand landmark model."""
import logging
import time
import urllib.request

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    RunningMode,
)

from .config import Config
from .hand_landmarks import Landmarks
from .hand_poses import palm_center
from .paths import MODEL_PATH

log = logging.getLogger(__name__)

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)
SECOND_HAND_CHECK_INTERVAL_S = 0.2  # while one hand is tracked, look for a second this often
TWO_HANDS_KEEP_TRACKING_S = 0.5  # keep the two-hand model this long after last seeing both hands


def download_model_if_missing():
    if MODEL_PATH.exists():
        return
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    log.info("Downloading hand model to %s", MODEL_PATH)
    partial_path = MODEL_PATH.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, partial_path)
    partial_path.replace(MODEL_PATH)  # only a complete download gets the real name


class _Landmarker:
    """One MediaPipe hand landmarker in VIDEO mode, which needs strictly increasing timestamps."""

    def __init__(self, config: Config, max_hands: int):
        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=RunningMode.VIDEO,
            num_hands=max_hands,
            min_hand_detection_confidence=config.min_detection_confidence,
            min_hand_presence_confidence=config.min_detection_confidence,
            min_tracking_confidence=config.min_tracking_confidence,
        )
        self._landmarker = HandLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1

    def detect(self, image: mp.Image) -> list[Landmarks]:
        timestamp_ms = max(int(time.monotonic() * 1000), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        return [[(point.x, point.y, point.z) for point in hand] for hand in result.hand_landmarks]

    def close(self):
        self._landmarker.close()


class HandTracker:
    """Finds up to two hands in each frame.

    Tracking two hands costs 2-4x more per frame, because MediaPipe keeps searching for
    the second one. So the one-hand model runs by default, the two-hand model checks for
    a second hand now and then, and takes over while both hands are up.
    Use as a context manager so the models are released when done.
    """

    def __init__(self, config: Config):
        download_model_if_missing()
        self._one_hand_model = _Landmarker(config, max_hands=1)
        self._two_hand_model = _Landmarker(config, max_hands=2)
        self._hands_in_last_frame = 0
        self._last_second_hand_check = float("-inf")
        self._two_hands_last_seen_time = float("-inf")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._one_hand_model.close()
        self._two_hand_model.close()

    def find_hands(self, bgr_frame, look_for_second_hand: bool = True) -> list[Landmarks]:
        """Return the landmarks of each hand in the frame (none, one or two), ordered left to right.

        With look_for_second_hand False, a lone hand skips the periodic search for a second
        one, which makes those frames several times slower.
        """
        rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        now = time.monotonic()
        if self._should_use_two_hand_model(now, look_for_second_hand):
            hands = self._two_hand_model.detect(image)
            self._last_second_hand_check = now
            if len(hands) == 2:
                self._two_hands_last_seen_time = now
        else:
            hands = self._one_hand_model.detect(image)
        self._hands_in_last_frame = len(hands)
        return sorted(hands, key=lambda hand: palm_center(hand)[0])

    def _should_use_two_hand_model(self, now: float, look_for_second_hand: bool) -> bool:
        if now - self._two_hands_last_seen_time < TWO_HANDS_KEEP_TRACKING_S:
            return True
        # With no hand in view, the one-hand model's own search finds the first hand.
        one_hand_tracked = self._hands_in_last_frame == 1
        return (look_for_second_hand and one_hand_tracked
                and now - self._last_second_hand_check >= SECOND_HAND_CHECK_INTERVAL_S)
