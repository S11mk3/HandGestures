import pytest

from handgestures.cursor_motion import CursorMapper, acceleration_gain
from handgestures.gestures import Gesture
from handgestures.hand_poses import Pose
from handgestures.pointer_driver import PointerController, PointerDriver
from handgestures.pointer_gestures import OneEuroFilter, PointerGestures, pinch_ratio

from synthetic_hands import FRAME_INTERVAL_S, make_hand

APART, PINCHED = 0.8, 0.1  # thumb-to-index gaps, in palm lengths


def pointer() -> PointerGestures:
    return PointerGestures(pinch_distance=0.3, double_pinch_s=0.5, min_cutoff_hz=2.0, speed_coefficient=30.0)


def feed(gestures: PointerGestures, gaps, start_time=0.0, at=(0.5, 0.8)):
    """Feed one frame per thumb gap; return (events, time after)."""
    events, now = [], start_time
    for gap in gaps:
        events += gestures.update(make_hand(Pose.POINTING, *at, pinch_gap=gap), now)
        now += FRAME_INTERVAL_S
    return events, now


@pytest.mark.parametrize("rotation", [None, ("x", 50), ("y", 50)])
def test_pinch_ratio_ignores_turning_the_hand(rotation):
    hand = make_hand(Pose.POINTING, rotation=rotation, pinch_gap=0.5)
    assert pinch_ratio(hand) == pytest.approx(0.5, abs=0.01)


def test_pinch_clicks_once_and_holds_the_pointer_still():
    gestures = pointer()
    feed(gestures, [APART] * 5)
    position = gestures.position
    events, now = feed(gestures, [PINCHED] * 10)
    assert [event.gesture for event in events] == [Gesture.PINCH]
    assert gestures.position == position


def test_hand_that_arrives_pinched_does_not_click():
    gestures = pointer()
    events, now = feed(gestures, [PINCHED] * 10)
    assert events == []
    events, _ = feed(gestures, [APART] * 3 + [PINCHED] * 3, now)
    assert [event.gesture for event in events] == [Gesture.PINCH]


def test_two_quick_pinches_double_click():
    gestures = pointer()
    events, _ = feed(gestures, [APART] * 5 + [PINCHED] * 3 + [APART] * 3 + [PINCHED] * 3)
    assert [event.gesture for event in events] == [Gesture.PINCH, Gesture.DOUBLE_PINCH]


def test_slow_second_pinch_is_a_new_click():
    gestures = pointer()
    events, _ = feed(gestures, [APART] * 5 + [PINCHED] * 3 + [APART] * 20 + [PINCHED] * 3)
    assert [event.gesture for event in events] == [Gesture.PINCH, Gesture.PINCH]


def test_click_aims_where_the_thumb_started_closing():
    gestures = pointer()
    _, now = feed(gestures, [APART] * 5)
    aim_time = now - FRAME_INTERVAL_S  # the last frame with the fingers fully apart
    events, _ = feed(gestures, [0.6, 0.45, 0.35, PINCHED], now)
    assert events[0].aim_time == pytest.approx(aim_time)


def test_letting_go_of_a_pinch_starts_a_new_segment():
    gestures = pointer()
    _, now = feed(gestures, [APART] * 5 + [PINCHED] * 3)
    segment = gestures.segment
    feed(gestures, [APART], now)
    assert gestures.segment != segment


def test_one_euro_filter_hides_jitter_but_follows_fast_moves():
    still, moving = OneEuroFilter(2.0, 30.0), OneEuroFilter(2.0, 30.0)
    jittered = [still.smooth((0.5 + (0.004 if i % 2 else -0.004), 0.5), i / 30) for i in range(30)]
    assert max(abs(x - 0.5) for x, _ in jittered[10:]) < 0.002
    for i in range(10):
        x, _ = moving.smooth((0.5 + 0.02 * i, 0.5), i / 30)
    assert x > 0.5 + 0.02 * 9 - 0.03  # lags by under a frame and a half of travel


def test_acceleration_gain():
    assert acceleration_gain(0.3, 0.0) == 1.0
    slow, fast = acceleration_gain(0.01, 1.0), acceleration_gain(2.0, 1.0)
    assert slow < 1 < fast == 2.0
    speeds = [i / 10 for i in range(12)]
    gains = [acceleration_gain(speed, 1.0) for speed in speeds]
    assert gains == sorted(gains)


def mapper(acceleration=0.0) -> CursorMapper:
    cursor_mapper = CursorMapper(speed=1.0, acceleration=acceleration, screen_width=1000, bounds=(0, 0, 1000, 800))
    cursor_mapper.start((500, 400))
    return cursor_mapper


def test_cursor_moves_by_how_far_the_hand_moves():
    cursor_mapper = mapper()
    cursor_mapper.update((0.5, 0.5), 1, 1.0, 0.0)
    assert cursor_mapper.update((0.6, 0.45), 1, 1.0, 0.1) == pytest.approx((600, 350))


def test_far_hand_moves_the_cursor_as_much_as_a_near_one():
    cursor_mapper = mapper()
    cursor_mapper.update((0.5, 0.5), 1, 0.5, 0.0)
    assert cursor_mapper.update((0.55, 0.5), 1, 0.5, 0.1) == pytest.approx((600, 400))


def test_cursor_stays_on_screen_and_comes_back_at_once():
    cursor_mapper = mapper()
    cursor_mapper.update((0.5, 0.5), 1, 1.0, 0.0)
    assert cursor_mapper.update((1.5, 0.5), 1, 1.0, 0.1) == (999, 400)
    assert cursor_mapper.update((1.4, 0.5), 1, 1.0, 0.2) == pytest.approx((899, 400))


def test_new_segment_does_not_move_the_cursor():
    cursor_mapper = mapper()
    cursor_mapper.update((0.5, 0.5), 1, 1.0, 0.0)
    assert cursor_mapper.update((0.9, 0.5), 2, 1.0, 0.1) == (500, 400)


def test_rewind_returns_to_an_earlier_target():
    cursor_mapper = mapper()
    for i in range(5):
        cursor_mapper.update((0.5 + 0.01 * i, 0.5), 1, 1.0, i * 0.03)
    assert cursor_mapper.rewind_to(0.03) == pytest.approx((510, 400))
    assert cursor_mapper.target == pytest.approx((510, 400))


class FakeCursor:
    def __init__(self, position=(100, 100)):
        self.at = position
        self.clicks = []

    def position(self):
        return self.at

    def move(self, position):
        self.at = position

    def click(self):
        self.clicks.append(self.at)

    def screen_width(self):
        return 1000

    def bounds(self):
        return 0, 0, 1000, 800


def test_driver_glides_evenly_to_each_target():
    cursor = FakeCursor((100, 100))
    driver = PointerDriver(cursor, start_thread=False)
    driver.move_to((100, 100), 0.03)
    driver.step(0.0)
    driver._glide_start = 0.0  # pin the glide's start for the test
    driver.move_to((200, 100), 0.04)
    driver._glide_start = 0.0
    driver.step(0.02)
    assert cursor.at == (150, 100)
    driver.step(0.05)
    assert cursor.at == (200, 100)


def test_driver_lets_go_when_the_mouse_moves_the_cursor():
    cursor = FakeCursor((100, 100))
    driver = PointerDriver(cursor, start_thread=False)
    driver.move_to((120, 100), 0.0)
    assert driver.step(1.0)
    cursor.at = (400, 300)  # the user moved the mouse
    assert not driver.step(1.01)
    assert driver.take_interrupted()
    assert cursor.at == (400, 300)


def test_driver_clicks_at_the_requested_point():
    cursor = FakeCursor((100, 100))
    driver = PointerDriver(cursor, start_thread=False)
    driver.click((300, 200))
    driver._do_clicks()
    assert cursor.clicks == [(300, 200)]


def test_controller_starts_from_the_cursor_and_double_clicks_in_place():
    cursor = FakeCursor((500, 400))
    from handgestures.config import Config

    controller = PointerController(Config(), cursor)
    try:
        controller.update((0.5, 0.5), 1, 1.0, 0.0)
        assert controller._mapper.target == (500, 400)
        controller.click(aim_time=0.0)
        controller.double_click()
        controller._driver._do_clicks()
        assert cursor.clicks == [(500, 400), (500, 400)]
    finally:
        controller.close()
