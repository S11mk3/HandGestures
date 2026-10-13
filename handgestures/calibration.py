"""Calibration at start: checks the light, then measures the user's hand while they hold up an open palm.

What it measures (the hand's size in the frame, how much tracking jitters, how reliably hands are
found) tunes the gestures, and is saved so a skipped calibration can reuse the last one.
"""
import json
import logging
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from enum import Enum
from math import dist, sqrt
from pathlib import Path
from statistics import median

import numpy as np

from .hand_landmarks import Hand
from .hand_poses import REFERENCE_PALM_LENGTH, Pose, PoseReader, palm_length_in_frame, palm_position
from .image_tuning import (
    LOW_FRAME_RATE,
    LOW_FRAME_RATE_ADVICE,
    VERDICT_ADVICE,
    ImageTuner,
    Lighting,
    LightingVerdict,
    judge_lighting,
    measure_lighting,
)
from .paths import CALIBRATION_PATH
from .pointer_gestures import DEFAULT_POINTER_CUTOFF_HZ, TRACKED_POINT

log = logging.getLogger(__name__)

LIGHT_CHECK_S = 1.5
# A camera adjusts its exposure for a moment after it starts: the light is judged on frames after this.
EXPOSURE_SETTLE_S = 0.75
HAND_TIMEOUT_S = 12.0
HOLD_S = 1.5  # how long the open palm must be held still
HOLD_STILL_RADIUS = 0.04  # frame widths, at the reference hand size
# A hold survives the hand being missed (or misread) for this long: a camera that sometimes
# loses the hand is exactly when calibration should finish and make detection more lenient.
HOLD_DROPOUT_S = 0.3
# Jitter (frame widths, at the reference hand size) of a still hand for which the default pointer
# smoothing is right. Noisier cameras get more smoothing, steadier ones less.
REFERENCE_JITTER = 0.002
MIN_POINTER_CUTOFF_HZ, MAX_POINTER_CUTOFF_HZ = 0.7, 4.0
# If the hand is missed in more than 1 - LOW_DETECTION_RATE of frames while held up, hand
# detection gets more lenient by DETECTION_CONFIDENCE_STEP, down to MIN_DETECTION_CONFIDENCE.
LOW_DETECTION_RATE = 0.8
DETECTION_CONFIDENCE_STEP = 0.15
MIN_DETECTION_CONFIDENCE = 0.4


@dataclass(frozen=True)
class CalibrationProfile:
    """What calibration measured."""
    palm_length: float = REFERENCE_PALM_LENGTH  # in frame widths: the user's usual distance from the camera
    pointer_cutoff_hz: float = DEFAULT_POINTER_CUTOFF_HZ  # smoothing that hides this camera's jitter
    detection_confidence: float | None = None  # when set, overrides the setting: hands were hard to find
    measured_at: str = ""  # when, ISO 8601; empty for the defaults


def load_profile(path: Path | None = None) -> CalibrationProfile:
    path = path or CALIBRATION_PATH
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        known = {setting.name for setting in fields(CalibrationProfile)}
        return CalibrationProfile(**{name: value for name, value in saved.items() if name in known})
    except FileNotFoundError:
        return CalibrationProfile()
    except (OSError, ValueError, TypeError) as error:
        log.warning("Ignoring unreadable %s: %s", path, error)
        return CalibrationProfile()


def save_profile(profile: CalibrationProfile, path: Path | None = None):
    path = path or CALIBRATION_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")
    except OSError as error:
        log.warning("Could not save %s: %s", path, error)


class Step(Enum):
    LIGHT = "light"
    HAND = "hand"
    DONE = "done"


@dataclass(frozen=True)
class CalibrationStatus:
    """Where calibration is, for the calibration window."""
    step: Step
    progress: float  # 0-1 through the current step
    instruction: str  # what the user should do now
    advice: tuple[str, ...] = ()  # problems found, and how to fix them
    lighting: LightingVerdict | None = None
    hand_measured: bool = False  # DONE only: the hand was measured (not skipped or timed out)


class Calibration:
    """Call update() with each camera frame until `finished`; then `profile` holds the result."""

    def __init__(self, tuner: ImageTuner, previous: CalibrationProfile, detection_confidence: float):
        self._tuner = tuner
        self._previous = previous
        self._detection_confidence = detection_confidence
        self.profile = previous
        self._step = Step.LIGHT
        self._step_start: float | None = None  # starts with the first frame: the camera may take a while
        self._light_samples: list[tuple[float, Lighting]] = []
        self._frame_count = 0
        self._fps: float | None = None
        self._lighting: LightingVerdict | None = None
        self._status = CalibrationStatus(Step.LIGHT, 0.0, "Checking the light…")
        # Hand step
        self._pose_reader = PoseReader()
        self._first_hand_time: float | None = None
        self._frames_since_first_hand = 0
        self._frames_with_hand = 0
        self._hold_start: float | None = None
        self._last_open_palm_time = float("-inf")
        self._hold_palm = (0.0, 0.0)
        self._hold_samples: list[tuple[float, tuple[float, float]]] = []  # (palm length, tracked point)

    @property
    def finished(self) -> bool:
        return self._step is Step.DONE

    @property
    def status(self) -> CalibrationStatus:
        return self._status

    def update(self, raw_image: np.ndarray, hands: list[Hand], now: float) -> CalibrationStatus:
        """Feed one frame (before brightening) and the hands found in it."""
        if self._step_start is None:
            self._step_start = now
        self._frame_count += 1
        if self._step is Step.LIGHT:
            self._check_light(raw_image, now)
        elif self._step is Step.HAND:
            if self._tuner.lighting is not None:
                self._lighting = judge_lighting(self._tuner.lighting)  # the user may fix the light meanwhile
            self._measure_hand(hands, now)
        return self._status

    def skip(self, now: float):
        if not self.finished:
            self._finish(None, now, "Calibration skipped. Using your previous calibration.")

    def _check_light(self, raw_image: np.ndarray, now: float):
        elapsed = now - self._step_start
        self._light_samples.append((elapsed, measure_lighting(raw_image)))
        if elapsed < LIGHT_CHECK_S:
            self._status = CalibrationStatus(Step.LIGHT, elapsed / LIGHT_CHECK_S, "Checking the light…")
            return
        settled = [lighting for time, lighting in self._light_samples if time >= EXPOSURE_SETTLE_S]
        settled = settled or [self._light_samples[-1][1]]
        lighting = Lighting(*(median(getattr(sample, name.name) for sample in settled)
                              for name in fields(Lighting)))
        self._lighting = judge_lighting(lighting)
        self._fps = self._frame_count / elapsed
        self._tuner.calibrate(lighting)
        log.info("Calibration: light %s (median %.0f, center %.0f, edges %.0f), %.0f fps, gamma %.2f",
                 self._lighting.value, lighting.median, lighting.center, lighting.edges, self._fps, self._tuner.gamma)
        self._step, self._step_start = Step.HAND, now
        self._measure_hand([], now)

    def _measure_hand(self, hands: list[Hand], now: float):
        if now - self._step_start >= HAND_TIMEOUT_S:
            message = ("No open hand was seen. Using your previous calibration." if self._first_hand_time is None
                       else "Couldn't hold the hand still long enough. Using your previous calibration.")
            self._finish(None, now, message)
            return

        hand = hands[0] if hands else None
        if self._first_hand_time is None and hand is not None:
            self._first_hand_time = now
        if self._first_hand_time is not None:
            self._frames_since_first_hand += 1
            self._frames_with_hand += hand is not None

        open_palm = hand is not None and self._pose_reader.read(hand) is Pose.OPEN_PALM
        if not open_palm:
            if self._hold_start is not None and now - self._last_open_palm_time <= HOLD_DROPOUT_S:
                return  # probably a missed frame: keep holding
            self._restart_hold()
            if hand is None:
                self._pose_reader.reset()
                self._show_hand_step(0.0, "Hold up one open hand, palm toward the camera, "
                                          "about where you'll usually make gestures.")
            else:
                self._show_hand_step(0.0, "Open your hand fully, with your fingers spread.")
            return
        self._last_open_palm_time = now

        palm_length = palm_length_in_frame(hand)
        palm = palm_position(hand)
        scale = palm_length / REFERENCE_PALM_LENGTH
        if self._hold_start is None or dist(palm, self._hold_palm) > HOLD_STILL_RADIUS * scale:
            self._hold_start, self._hold_palm = now, palm
            self._hold_samples.clear()
        self._hold_samples.append((palm_length, hand.point(TRACKED_POINT)))
        progress = (now - self._hold_start) / HOLD_S
        if progress >= 1 and len(self._hold_samples) >= 5:
            self._finish(self._measured_profile(), now, "All set! Gestures are tuned to your hand and light.")
        else:
            self._show_hand_step(min(progress, 1.0), "Hold still…")

    def _restart_hold(self):
        self._hold_start = None
        self._hold_samples.clear()

    def _measured_profile(self) -> CalibrationProfile:
        palm_length = median(length for length, _ in self._hold_samples)
        points = np.array([point for _, point in self._hold_samples])
        # Frame-to-frame differences of a still point with independent noise σ spread by σ√2.
        jitter = float(np.mean(np.std(np.diff(points, axis=0), axis=0))) / sqrt(2)
        jitter /= palm_length / REFERENCE_PALM_LENGTH  # as if at the reference distance
        cutoff = DEFAULT_POINTER_CUTOFF_HZ * sqrt(REFERENCE_JITTER / max(jitter, 1e-6))
        cutoff = min(max(cutoff, MIN_POINTER_CUTOFF_HZ), MAX_POINTER_CUTOFF_HZ)

        detection_rate = self._frames_with_hand / max(self._frames_since_first_hand, 1)
        detection_confidence = None
        if detection_rate < LOW_DETECTION_RATE:
            detection_confidence = max(self._detection_confidence - DETECTION_CONFIDENCE_STEP,
                                       MIN_DETECTION_CONFIDENCE)
        log.info("Calibration: palm length %.3f, jitter %.4f -> smoothing %.1f Hz, hand found in %.0f%% of frames",
                 palm_length, jitter, cutoff, 100 * detection_rate)
        return CalibrationProfile(
            palm_length=palm_length,
            pointer_cutoff_hz=cutoff,
            detection_confidence=detection_confidence,
            measured_at=datetime.now().isoformat(timespec="seconds"),
        )

    def _show_hand_step(self, progress: float, instruction: str):
        self._status = CalibrationStatus(Step.HAND, progress, instruction, self._advice(), self._lighting)

    def _finish(self, measured: CalibrationProfile | None, now: float, message: str):
        self._step = Step.DONE
        self.profile = measured or self._previous
        advice = self._advice()
        if measured and measured.detection_confidence is not None:
            advice += ("The hand was sometimes hard to find, so detection is now more lenient.",)
        self._status = CalibrationStatus(Step.DONE, 1.0, message, advice, self._lighting, measured is not None)

    def _advice(self) -> tuple[str, ...]:
        advice = []
        if self._lighting is not None and VERDICT_ADVICE[self._lighting]:
            advice.append(VERDICT_ADVICE[self._lighting])
        if (self._fps is not None and self._fps < LOW_FRAME_RATE
                and self._lighting is not LightingVerdict.NO_PICTURE):
            advice.append(LOW_FRAME_RATE_ADVICE.format(fps=self._fps))
        return tuple(advice)
