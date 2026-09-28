import pytest

from handgestures.config import DEFAULTS
from handgestures.gestures import Event, GestureEngine, Pose, classify

FPS = 30
DT = 1 / FPS

# Offsets from the wrist for an upright right hand, fingers pointing up (-y).
MCP = {5: (-0.06, -0.15), 9: (-0.02, -0.16), 13: (0.02, -0.15), 17: (0.06, -0.13)}
PIP = {6: (-0.07, -0.22), 10: (-0.02, -0.24), 14: (0.03, -0.22), 18: (0.07, -0.19)}
TIP_EXTENDED = {8: (-0.08, -0.32), 12: (-0.02, -0.35), 16: (0.04, -0.32), 20: (0.09, -0.27)}
TIP_CURLED = {8: (-0.05, -0.11), 12: (-0.02, -0.11), 16: (0.02, -0.10), 20: (0.05, -0.09)}
THUMB = {1: (-0.05, -0.04), 2: (-0.09, -0.07), 3: (-0.12, -0.10), 4: (-0.14, -0.13)}

EXTENDED_BY_POSE = {
    Pose.OPEN_PALM: (True, True, True, True),
    Pose.FIST: (False, False, False, False),
    Pose.TWO_FINGERS: (True, True, False, False),
    Pose.OTHER: (True, False, False, False),
}


def hand(pose: Pose, wx=0.5, wy=0.8):
    offsets = {0: (0.0, 0.0), **THUMB, **MCP, **PIP}
    for ext, tip in zip(EXTENDED_BY_POSE[pose], (8, 12, 16, 20)):
        offsets[tip] = (TIP_EXTENDED if ext else TIP_CURLED)[tip]
    for pip, tip in ((6, 8), (10, 12), (14, 16), (18, 20)):
        dip = pip + 1
        offsets[dip] = tuple((a + b) / 2 for a, b in zip(offsets[pip], offsets[tip]))
    return [(wx + offsets[i][0], wy + offsets[i][1], 0.0) for i in range(21)]


class Sim:
    def __init__(self, **overrides):
        self.engine = GestureEngine({**DEFAULTS, **overrides})
        self.t = 0.0

    def frames(self, pose, start, end, n, paused=False):
        """Move the wrist linearly from start to end over n frames; return all events."""
        events = []
        for i in range(n):
            f = i / max(n - 1, 1)
            x = start[0] + (end[0] - start[0]) * f
            y = start[1] + (end[1] - start[1]) * f
            events += self.engine.update(hand(pose, x, y), self.t, paused)
            self.t += DT
        return events

    def hold(self, pose, n, at=(0.5, 0.8), paused=False):
        return self.frames(pose, at, at, n, paused)

    def gap(self, seconds):
        events = []
        for _ in range(round(seconds * FPS)):
            events += self.engine.update(None, self.t)
            self.t += DT
        return events


@pytest.mark.parametrize("pose", list(Pose))
def test_classify(pose):
    assert classify(hand(pose)) is pose


@pytest.mark.parametrize(
    "start,end,kind",
    [
        ((0.5, 0.5), (0.5, 0.85), "SWIPE_DOWN"),
        ((0.5, 0.85), (0.5, 0.5), "SWIPE_UP"),
        ((0.7, 0.7), (0.3, 0.7), "SWIPE_LEFT"),
        ((0.3, 0.7), (0.7, 0.7), "SWIPE_RIGHT"),
    ],
)
def test_swipe_directions(start, end, kind):
    sim = Sim()
    sim.hold(Pose.OPEN_PALM, 5, at=start)
    assert sim.frames(Pose.OPEN_PALM, start, end, 8) == [Event(kind)]


def test_slow_drift_is_not_a_swipe():
    sim = Sim()
    assert sim.frames(Pose.OPEN_PALM, (0.3, 0.7), (0.7, 0.7), 90) == []


def test_diagonal_is_not_a_swipe():
    sim = Sim()
    sim.hold(Pose.OPEN_PALM, 5, at=(0.3, 0.5))
    assert sim.frames(Pose.OPEN_PALM, (0.3, 0.5), (0.6, 0.8), 8) == []


def test_unstable_pose_does_not_swipe():
    sim = Sim()
    # Hand appears already moving: the first stable_frames frames are ignored,
    # leaving too little travel to count.
    assert sim.frames(Pose.OPEN_PALM, (0.3, 0.7), (0.52, 0.7), 5) == []


def test_return_stroke_does_not_fire_opposite():
    sim = Sim()
    sim.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7))
    assert sim.frames(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8) == [Event("SWIPE_LEFT")]
    # Bring the hand back quickly to where it started.
    assert sim.frames(Pose.OPEN_PALM, (0.3, 0.7), (0.7, 0.7), 10) == []


def test_same_direction_allowed_after_cooldown():
    sim = Sim()
    sim.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7))
    assert sim.frames(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8) == [Event("SWIPE_LEFT")]
    sim.gap(1.0)
    sim.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7))
    assert sim.frames(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8) == [Event("SWIPE_LEFT")]


def test_fist_hold_plays_pauses_once_until_released():
    sim = Sim()
    assert sim.hold(Pose.FIST, 25) == []  # < 1 s
    assert sim.hold(Pose.FIST, 60) == [Event("PLAY_PAUSE")]
    sim.hold(Pose.OPEN_PALM, 3)
    assert sim.hold(Pose.FIST, 40) == [Event("PLAY_PAUSE")]


def test_paused_emits_nothing():
    sim = Sim()
    sim.hold(Pose.OPEN_PALM, 5, at=(0.7, 0.7), paused=True)
    assert sim.frames(Pose.OPEN_PALM, (0.7, 0.7), (0.3, 0.7), 8, paused=True) == []
    sim.hold(Pose.TWO_FINGERS, 5, paused=True)
    assert sim.frames(Pose.TWO_FINGERS, (0.5, 0.8), (0.5, 0.5), 10, paused=True) == []
    assert sim.hold(Pose.FIST, 40, paused=True) == []


def test_scroll_steps_follow_hand():
    sim = Sim()
    sim.hold(Pose.TWO_FINGERS, 5)
    up = sim.frames(Pose.TWO_FINGERS, (0.5, 0.8), (0.5, 0.61), 20)
    assert all(e.kind == "SCROLL" and e.value > 0 for e in up)
    assert sum(e.value for e in up) == 6  # 0.19 of travel at 0.03 per step
    down = sim.frames(Pose.TWO_FINGERS, (0.5, 0.61), (0.5, 0.755), 20)
    assert sum(e.value for e in down) == -4


def test_losing_hand_resets_state():
    sim = Sim()
    sim.hold(Pose.FIST, 20)
    sim.gap(0.2)
    assert sim.hold(Pose.FIST, 20) == []  # the hold timer restarted
