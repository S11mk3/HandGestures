import numpy as np
import pytest

from handgestures.image_tuning import (
    TARGET_BRIGHTNESS,
    ImageTuner,
    LightingVerdict,
    gamma_for,
    judge_lighting,
    measure_lighting,
)


def uniform(level: int) -> np.ndarray:
    return np.full((480, 640, 3), level, dtype=np.uint8)


def backlit() -> np.ndarray:
    """Bright surroundings (a window) around a dim middle (the user)."""
    image = uniform(235)
    image[120:360, 160:480] = 60
    return image


@pytest.mark.parametrize("image,verdict", [
    (uniform(0), LightingVerdict.NO_PICTURE),
    (uniform(15), LightingVerdict.TOO_DARK),
    (uniform(55), LightingVerdict.DIM),
    (uniform(120), LightingVerdict.GOOD),
    (uniform(235), LightingVerdict.OVEREXPOSED),
    (backlit(), LightingVerdict.BACKLIT),
])
def test_verdicts(image, verdict):
    assert judge_lighting(measure_lighting(image)) is verdict


def test_dim_picture_is_brightened_to_the_target():
    tuner = ImageTuner()
    image = uniform(55)
    tuner.calibrate(measure_lighting(image))
    assert tuner.gamma < 1
    assert abs(int(np.median(tuner.apply(image))) - TARGET_BRIGHTNESS) <= 3


def test_well_lit_picture_is_left_alone():
    tuner = ImageTuner()
    image = uniform(118)
    tuner.calibrate(measure_lighting(image))
    assert tuner.apply(image) is image


def test_backlit_picture_brightens_the_middle_and_equalizes():
    lighting = measure_lighting(backlit())
    assert gamma_for(lighting) < 0.7  # judged by the middle, not the bright surroundings
    tuner = ImageTuner()
    tuner.calibrate(lighting)
    assert tuner.equalize


def test_black_picture_is_not_corrected():
    assert gamma_for(measure_lighting(uniform(0))) == 1.0


def test_tuner_follows_the_light_gradually():
    tuner = ImageTuner()
    tuner.observe(uniform(55), 0.0)  # first look: corrects at once
    dim_gamma = tuner.gamma
    tuner.observe(uniform(118), 0.6)  # a lamp goes on
    assert dim_gamma < tuner.gamma < 1.0
    for i in range(2, 40):
        tuner.observe(uniform(118), i * 0.6)
    assert tuner.gamma == pytest.approx(1.0, abs=0.04)


def test_normally_lit_picture_is_not_darkened():
    # A camera's own exposure is best for anything between dim and glaring.
    assert gamma_for(measure_lighting(uniform(142))) == 1.0
    assert gamma_for(measure_lighting(uniform(235))) > 1.0
