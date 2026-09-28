"""The steps of a guided recording session, and what each one should detect."""
from dataclasses import dataclass

from handgestures.gestures import Gesture


@dataclass(frozen=True)
class Step:
    label: str  # saved with every frame recorded during the step
    prompt: str  # shown in the preview; keep it under ~40 characters
    seconds: float
    expected_gesture: Gesture | None  # None: nothing should be detected
    expected_count: int | None = None  # None: any number of times


GET_READY_S = 4
GET_READY_LABEL = "get_ready"

STEPS = [
    Step("swipe_left", "Open palm: swipe LEFT x5", 15, Gesture.SWIPE_LEFT, 5),
    Step("swipe_right", "Open palm: swipe RIGHT x5", 15, Gesture.SWIPE_RIGHT, 5),
    Step("swipe_up", "Open palm: swipe UP x5", 15, Gesture.SWIPE_UP, 5),
    Step("swipe_down", "Open palm: swipe DOWN x5", 15, Gesture.SWIPE_DOWN, 5),
    Step("fist_hold", "Hold a fist 1 s, then open. x4", 16, Gesture.FIST_HOLD, 4),
    Step("scroll", "Two fingers: scroll up, then down", 15, Gesture.SCROLL),
    Step("hands_apart", "Two open palms: move APART x5", 20, Gesture.HANDS_APART, 5),
    Step("hands_together", "Two open palms: move TOGETHER x5", 20, Gesture.HANDS_TOGETHER, 5),
    Step("natural", "No gestures: type, touch face, use mouse", 30, None, 0),
]
