"""Finds hands in camera frames with MediaPipe's hand landmark model."""
import logging
import urllib.request

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    RunningMode,
)

from .hand_landmarks import Hand, Landmarks
from .hand_poses import palm_center
from .paths import MODEL_PATH

log = logging.getLogger(__name__)

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)
MODEL_DOWNLOAD_TIMEOUT_S = 30
SECOND_HAND_CHECK_INTERVAL_S = 0.2  # while one hand is tracked, look for a second this often
TWO_HANDS_KEEP_TRACKING_S = 0.5  # keep the two-hand model this long after last seeing both hands
# Two hands whose outlines overlap by more than this (intersection over union) are one hand
# reported twice, as MediaPipe sometimes does during fast moves.
DUPLICATE_HAND_OVERLAP = 0.5


def download_model_if_missing():
    if MODEL_PATH.exists():
        return
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    log.info("Downloading hand model to %s", MODEL_PATH)
    partial_path = MODEL_PATH.with_suffix(".part")
    with urllib.request.urlopen(MODEL_URL, timeout=MODEL_DOWNLOAD_TIMEOUT_S) as response:
        partial_path.write_bytes(response.read())
    partial_path.replace(MODEL_PATH)  # only a complete download gets the real name


class _Landmarker:
    """One MediaPipe hand landmarker in VIDEO mode, which needs strictly increasing timestamps."""

    def __init__(self, max_hands: int, detection_confidence: float, tracking_confidence: float):
        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=RunningMode.VIDEO,
            num_hands=max_hands,
            min_hand_detection_confidence=detection_confidence,
            min_hand_presence_confidence=detection_confidence,
            min_tracking_confidence=tracking_confidence,
        )
        self._landmarker = HandLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1

    def detect(self, image: mp.Image, timestamp_s: float, aspect: float) -> list[Hand]:
        timestamp_ms = max(int(timestamp_s * 1000), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        hands = []
        for image_points, world_points, handedness in zip(
                result.hand_landmarks, result.hand_world_landmarks, result.handedness):
            category = handedness[0] if handedness else None
            hands.append(Hand(
                image=[(point.x, point.y, point.z) for point in image_points],
                world=[(point.x, point.y, point.z) for point in world_points],
                aspect=aspect,
                handedness=category.category_name if category else "",
                score=category.score if category else 0.0,
            ))
        return hands

    def close(self):
        self._landmarker.close()


class HandTracker:
    """Finds up to two hands in each frame.

    Tracking two hands costs 2-4x more per frame, because MediaPipe keeps searching for
    the second one. So the one-hand model runs by default, the two-hand model checks for
    a second hand now and then, and takes over while both hands are up.
    Use as a context manager so the models are released when done.
    """

    def __init__(self, detection_confidence: float, tracking_confidence: float):
        download_model_if_missing()
        self.detection_confidence = detection_confidence
        self.tracking_confidence = tracking_confidence
        self._one_hand_model = _Landmarker(1, detection_confidence, tracking_confidence)
        self._two_hand_model = _Landmarker(2, detection_confidence, tracking_confidence)
        self._hands_in_last_frame = 0
        self._last_second_hand_check = float("-inf")
        self._two_hands_last_seen_time = float("-inf")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def close(self):
        self._one_hand_model.close()
        self._two_hand_model.close()

    def find_hands(self, bgr_frame, timestamp_s: float, look_for_second_hand: bool = True) -> list[Hand]:
        """Return each hand in the frame (none, one or two), ordered left to right.

        `timestamp_s` is when the frame was captured (time.monotonic()). With
        look_for_second_hand False, a lone hand skips the periodic search for a second one,
        which makes those frames several times slower.
        """
        height, width = bgr_frame.shape[:2]
        rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        if self._should_use_two_hand_model(timestamp_s, look_for_second_hand):
            hands = remove_duplicate_hands(self._two_hand_model.detect(image, timestamp_s, height / width))
            self._last_second_hand_check = timestamp_s
            if len(hands) == 2:
                self._two_hands_last_seen_time = timestamp_s
        else:
            hands = self._one_hand_model.detect(image, timestamp_s, height / width)
        self._hands_in_last_frame = len(hands)
        return sorted(hands, key=lambda hand: palm_center(hand.image)[0])

    def _should_use_two_hand_model(self, now: float, look_for_second_hand: bool) -> bool:
        if now - self._two_hands_last_seen_time < TWO_HANDS_KEEP_TRACKING_S:
            return True
        # With no hand in view, the one-hand model's own search finds the first hand.
        one_hand_tracked = self._hands_in_last_frame == 1
        return (look_for_second_hand and one_hand_tracked
                and now - self._last_second_hand_check >= SECOND_HAND_CHECK_INTERVAL_S)


def remove_duplicate_hands(hands: list[Hand]) -> list[Hand]:
    """The hands, without second copies of the same hand (keeping the copy MediaPipe is surer of)."""
    if len(hands) < 2:
        return hands
    first, second = hands[0], hands[1]
    if _overlap(_bounds(first.image), _bounds(second.image)) > DUPLICATE_HAND_OVERLAP:
        return [max(first, second, key=lambda hand: hand.score)]
    return hands


def _bounds(landmarks: Landmarks) -> tuple[float, float, float, float]:
    xs = [x for x, _, _ in landmarks]
    ys = [y for _, y, _ in landmarks]
    return min(xs), min(ys), max(xs), max(ys)


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Intersection over union of two (left, top, right, bottom) rectangles."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    intersection = width * height
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return intersection / (area_a + area_b - intersection)
