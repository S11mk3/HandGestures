"""Judging how well lit the camera image is, and brightening dim images for hand tracking."""
from dataclasses import dataclass
from enum import Enum
from math import exp, log

import cv2
import numpy as np

THUMBNAIL_SIZE = (80, 60)  # measuring a tiny copy is just as telling, and ~100x cheaper
# Pictures darker than TARGET_BRIGHTNESS (median, 0-255) are brightened to it, and ones brighter
# than MAX_BRIGHTNESS darkened to that; anything in between is left as the camera made it.
TARGET_BRIGHTNESS = 115
MAX_BRIGHTNESS = 200
MIN_GAMMA, MAX_GAMMA = 0.4, 1.4  # brightening up to gamma 0.4; darkening only mildly
GAMMA_DEAD_ZONE = 0.06  # closer to 1 than this, leave the image as it is
MEASURE_INTERVAL_S = 0.5
ADAPT_S = 3.0  # time constant for following changes in the light
# Thresholds on 0-255 brightness:
BLACK_BRIGHT_LEVEL = 12  # a picture whose brightest parts are below this is black
TOO_DARK_MEDIAN = 30
DIM_MEDIAN = 80
OVEREXPOSED_MEDIAN = 215
BACKLIT_EDGE_LEVEL = 150  # bright surroundings...
BACKLIT_CONTRAST = 50  # ...this much brighter than the middle, where the user is
LOW_FRAME_RATE = 20.0  # frames per second; webcams slow down like this when there's too little light


@dataclass(frozen=True)
class Lighting:
    """Brightness (0-255) statistics of one camera image."""
    median: float
    dark: float  # 5th percentile
    bright: float  # 95th percentile
    center: float  # median of the middle of the image, where the user usually is
    edges: float  # median of the border around it

    @property
    def is_black(self) -> bool:
        return self.bright < BLACK_BRIGHT_LEVEL

    @property
    def is_backlit(self) -> bool:
        return self.edges > BACKLIT_EDGE_LEVEL and self.edges - self.center > BACKLIT_CONTRAST


def measure_lighting(image: np.ndarray) -> Lighting:
    small = cv2.resize(image, THUMBNAIL_SIZE, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    dark, median, bright = np.percentile(gray, (5, 50, 95))
    height, width = gray.shape
    middle = np.zeros(gray.shape, dtype=bool)
    middle[height // 4: height * 3 // 4, width // 4: width * 3 // 4] = True
    return Lighting(float(median), float(dark), float(bright),
                    float(np.median(gray[middle])), float(np.median(gray[~middle])))


class LightingVerdict(Enum):
    GOOD = "good"
    DIM = "dim"
    TOO_DARK = "too dark"
    BACKLIT = "backlit"
    OVEREXPOSED = "overexposed"
    NO_PICTURE = "no picture"


# What to tell the user about each verdict. GOOD needs no advice.
VERDICT_ADVICE = {
    LightingVerdict.GOOD: "",
    LightingVerdict.DIM: "The room is a bit dim, so the picture is brightened automatically. "
                         "More light makes tracking more reliable.",
    LightingVerdict.TOO_DARK: "It's very dark. Turn on a light so the camera can see your hand.",
    LightingVerdict.BACKLIT: "There's bright light behind you. Face a window or lamp instead, "
                             "or close the blinds behind you.",
    LightingVerdict.OVEREXPOSED: "The picture is very bright. Move out of direct sunlight.",
    LightingVerdict.NO_PICTURE: "The camera picture is black. Open the camera's privacy shutter, "
                                "or check that the camera isn't switched off (some laptops have a camera key).",
}
LOW_FRAME_RATE_ADVICE = ("The camera delivers only {fps:.0f} pictures per second, often because the light is low. "
                         "More light makes the pointer smoother.")


def judge_lighting(lighting: Lighting) -> LightingVerdict:
    if lighting.is_black:
        return LightingVerdict.NO_PICTURE
    if lighting.is_backlit:
        return LightingVerdict.BACKLIT
    if lighting.median < TOO_DARK_MEDIAN:
        return LightingVerdict.TOO_DARK
    if lighting.median < DIM_MEDIAN:
        return LightingVerdict.DIM
    if lighting.median > OVEREXPOSED_MEDIAN:
        return LightingVerdict.OVEREXPOSED
    return LightingVerdict.GOOD


def gamma_for(lighting: Lighting) -> float:
    """The gamma that brings the picture's typical brightness within TARGET_BRIGHTNESS-MAX_BRIGHTNESS.

    With bright light behind the user, the middle of the picture (where the user is) counts.
    """
    if lighting.is_black:
        return 1.0  # nothing to bring out
    level = lighting.center if lighting.is_backlit else lighting.median
    level = min(max(level, 1.0), 254.0)
    if level < TARGET_BRIGHTNESS:
        target = TARGET_BRIGHTNESS
    elif level > MAX_BRIGHTNESS:
        target = MAX_BRIGHTNESS
    else:
        return 1.0
    gamma = log(target / 255) / log(level / 255)
    gamma = min(max(gamma, MIN_GAMMA), MAX_GAMMA)
    return 1.0 if abs(gamma - 1) < GAMMA_DEAD_ZONE else gamma


class ImageTuner:
    """Brightens dim camera images before hand tracking, following changes in the light.

    A gamma curve lifts shadows more than highlights. With bright light behind the user,
    local contrast equalization (CLAHE) also brings the hand out against the background.
    """

    def __init__(self):
        self.gamma = 1.0
        self.equalize = False
        self.lighting: Lighting | None = None
        self._last_measure_time: float | None = None
        self._lut: np.ndarray | None = None
        self._lut_gamma = 1.0
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    def calibrate(self, lighting: Lighting):
        """Correct for this lighting straight away."""
        self.lighting = lighting
        self._set_gamma(gamma_for(lighting))
        self.equalize = lighting.is_backlit

    def observe(self, image: np.ndarray, now: float):
        """Measure the uncorrected image now and then, easing the correction toward what it needs."""
        if self._last_measure_time is not None and now - self._last_measure_time < MEASURE_INTERVAL_S:
            return
        first_measure = self._last_measure_time is None
        elapsed = 0.0 if first_measure else now - self._last_measure_time
        self._last_measure_time = now
        lighting = measure_lighting(image)
        if first_measure:
            self.calibrate(lighting)
            return
        self.lighting = lighting
        # Ease in log space, so brightening and darkening change at the same pace.
        weight = 1 - exp(-elapsed / ADAPT_S)
        self._set_gamma(exp(log(self.gamma) + weight * (log(gamma_for(lighting)) - log(self.gamma))))
        self.equalize = lighting.is_backlit

    def apply(self, image: np.ndarray) -> np.ndarray:
        """The image as hand tracking should see it: brightened if needed, otherwise unchanged."""
        if self._lut is not None:
            image = cv2.LUT(image, self._lut)
        if self.equalize:
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            lab[:, :, 0] = self._clahe.apply(lab[:, :, 0])
            image = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        return image

    def _set_gamma(self, gamma: float):
        self.gamma = gamma
        if abs(gamma - 1) < GAMMA_DEAD_ZONE / 2:
            self._lut, self._lut_gamma = None, 1.0
            return
        if self._lut is not None and abs(gamma - self._lut_gamma) < 0.01:
            return  # not worth rebuilding the table
        levels = np.arange(256, dtype=np.float32) / 255
        self._lut = np.clip(255 * levels ** gamma + 0.5, 0, 255).astype(np.uint8)
        self._lut_gamma = gamma
