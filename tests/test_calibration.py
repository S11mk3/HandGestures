import numpy as np
import pytest

from hard2gesture.calibration import (
    HAND_TIMEOUT_S,
    LIGHT_CHECK_S,
    MAX_POINTER_CUTOFF_HZ,
    Calibration,
    CalibrationProfile,
    Step,
    load_profile,
    save_profile,
)
from hard2gesture.hand_poses import REFERENCE_PALM_LENGTH, Pose
from hard2gesture.image_tuning import ImageTuner, LightingVerdict

from synthetic_hands import FRAME_INTERVAL_S, make_hand

WELL_LIT = np.full((480, 640, 3), 120, dtype=np.uint8)
DIM = np.full((480, 640, 3), 50, dtype=np.uint8)
PREVIOUS = CalibrationProfile(palm_length=0.2, pointer_cutoff_hz=1.5, measured_at="2026-01-01T10:00:00")


class Run:
    """Feeds a Calibration frames at 30 fps."""

    def __init__(self, image=WELL_LIT):
        self.tuner = ImageTuner()
        self.calibration = Calibration(self.tuner, PREVIOUS, detection_confidence=0.6)
        self.image = image
        self.time = 0.0

    def frames(self, seconds, hand=None, every=1):
        """`every`: the hand is found in one of this many frames."""
        status = None
        for i in range(round(seconds / FRAME_INTERVAL_S)):
            if self.calibration.finished:
                break
            hands = [hand] if hand is not None and i % every == 0 else []
            status = self.calibration.update(self.image, hands, self.time)
            self.time += FRAME_INTERVAL_S
        return status


def test_light_check_then_hand():
    run = Run(DIM)
    status = run.frames(LIGHT_CHECK_S - 0.2)
    assert status.step is Step.LIGHT
    status = run.frames(0.3)
    assert status.step is Step.HAND
    assert status.lighting is LightingVerdict.DIM
    assert run.tuner.gamma < 1  # brightening started
    assert any("dim" in advice for advice in status.advice)


def test_holding_an_open_palm_still_measures_the_hand():
    run = Run()
    run.frames(LIGHT_CHECK_S + 0.1)
    status = run.frames(3.0, make_hand(Pose.OPEN_PALM, palm_length=REFERENCE_PALM_LENGTH * 0.8))
    assert status.step is Step.DONE and status.hand_measured
    profile = run.calibration.profile
    assert profile.palm_length == pytest.approx(REFERENCE_PALM_LENGTH * 0.8, rel=0.05)
    assert profile.pointer_cutoff_hz == MAX_POINTER_CUTOFF_HZ  # a perfectly steady synthetic hand
    assert profile.detection_confidence is None
    assert profile.measured_at


def test_a_fist_is_not_measured():
    run = Run()
    run.frames(LIGHT_CHECK_S + 0.1)
    status = run.frames(3.0, make_hand(Pose.FIST))
    assert status.step is Step.HAND
    assert "Open your hand" in status.instruction


def test_hand_that_is_often_missed_makes_detection_more_lenient():
    run = Run()
    run.frames(LIGHT_CHECK_S + 0.1)
    status = run.frames(4.0, make_hand(Pose.OPEN_PALM), every=2)  # found in half the frames
    assert status.step is Step.DONE and status.hand_measured
    assert run.calibration.profile.detection_confidence == pytest.approx(0.45)


def test_no_hand_times_out_and_keeps_the_previous_calibration():
    run = Run()
    status = run.frames(LIGHT_CHECK_S + HAND_TIMEOUT_S + 0.5)
    assert status.step is Step.DONE and not status.hand_measured
    assert run.calibration.profile == PREVIOUS
    assert "No open hand" in status.instruction


def test_skip_keeps_the_previous_calibration():
    run = Run()
    run.frames(0.5)
    run.calibration.skip(run.time)
    assert run.calibration.finished
    assert run.calibration.profile == PREVIOUS


def test_black_picture_advice():
    run = Run(np.zeros((480, 640, 3), dtype=np.uint8))
    status = run.frames(LIGHT_CHECK_S + 0.1)
    assert status.lighting is LightingVerdict.NO_PICTURE
    assert any("privacy shutter" in advice for advice in status.advice)


def test_profile_round_trip(tmp_path):
    path = tmp_path / "calibration.json"
    assert load_profile(path) == CalibrationProfile()  # none saved yet
    save_profile(PREVIOUS, path)
    assert load_profile(path) == PREVIOUS
    path.write_text("{broken")
    assert load_profile(path) == CalibrationProfile()
