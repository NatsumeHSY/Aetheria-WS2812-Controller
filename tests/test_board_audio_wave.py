import importlib
import sys
import unittest
from pathlib import Path


BOARD_DIR = Path(__file__).parents[1] / "board"


def load_audio_wave_module():
    board_path = str(BOARD_DIR)
    if board_path not in sys.path:
        sys.path.insert(0, board_path)
    return importlib.import_module("audio_wave")


class FakeClock:
    def __init__(self, value=0):
        self.value = value

    def __call__(self):
        return self.value


class FakeDriver:
    def __init__(self):
        self.writes = []
        self.shows = 0
        self.clears = 0

    def set_pixel(self, index, color, brightness=255, auto_write=False):
        self.writes.append((index, tuple(color), brightness, auto_write))

    def show(self):
        self.shows += 1

    def clear(self):
        self.clears += 1


class BoardAudioWaveTests(unittest.TestCase):
    def setUp(self):
        self.audio_wave = importlib.reload(load_audio_wave_module())

    def test_config_has_five_fixed_centers_and_normalizes_colors(self):
        config = self.audio_wave.AudioWaveConfig(
            colors=[(300, -1, 12), (1, 2, 3)],
            timing_ms=0,
        )

        self.assertEqual(config.centers, ((18, 1), (48, 4), (72, 2), (96, 4), (126, 1)))
        self.assertEqual(config.colors, ((255, 0, 12), (1, 2, 3)))
        self.assertEqual(config.timing_ms, 25)

    def test_state_uses_first_color_fallback_and_cycles_colors(self):
        one_color = self.audio_wave.AudioWaveState(
            self.audio_wave.AudioWaveConfig([(10, 20, 30)]),
            clock=FakeClock(),
        )
        many_colors = self.audio_wave.AudioWaveState(
            self.audio_wave.AudioWaveConfig([(10, 20, 30), (40, 50, 60)]),
            clock=FakeClock(),
        )

        self.assertEqual(one_color.center_colors(), ((10, 20, 30),) * 5)
        self.assertEqual(many_colors.center_colors(), (
            (10, 20, 30), (40, 50, 60), (10, 20, 30), (40, 50, 60), (10, 20, 30),
        ))

    def test_update_accepts_newer_frames_wraps_and_rejects_duplicate_or_late(self):
        state = self.audio_wave.AudioWaveState(
            self.audio_wave.AudioWaveConfig([(10, 20, 30)]),
            clock=FakeClock(),
        )
        frame = (1, 120, 30, (10, 20, 30, 40, 50, 60, 70, 80))

        self.assertTrue(state.update(*frame))
        self.assertFalse(state.update(*frame))
        self.assertFalse(state.update(0, 120, 30, frame[3]))

        wrapped = self.audio_wave.AudioWaveState(
            self.audio_wave.AudioWaveConfig([(10, 20, 30)]),
            clock=FakeClock(),
        )
        self.assertTrue(wrapped.update(0xFFFF, *frame[1:]))
        self.assertTrue(wrapped.update(0x0000, *frame[1:]))

    def test_render_advances_radius_decays_amplitude_and_clamps_sum(self):
        clock = FakeClock(100)
        state = self.audio_wave.AudioWaveState(
            self.audio_wave.AudioWaveConfig([(255, 0, 0), (0, 255, 0)]),
            clock=clock,
        )
        state.update(1, 255, 255, (255,) * 8)
        driver = FakeDriver()

        state.render_frame(driver, brightness=255, timing_ms=1)
        first_radius = state.wave_snapshot()[0][0]
        first_amplitude = state.wave_snapshot()[0][1]
        state.render_frame(driver, brightness=255, timing_ms=1)
        second_radius = state.wave_snapshot()[0][0]
        second_amplitude = state.wave_snapshot()[0][1]

        self.assertEqual(len(driver.writes), 864 * 2)
        self.assertGreater(second_radius, first_radius)
        self.assertLess(second_amplitude, first_amplitude)
        self.assertTrue(all(0 <= write[2] <= 255 for write in driver.writes))
        self.assertEqual(driver.shows, 2)

    def test_render_keeps_the_first_color_as_a_constant_base(self):
        state = self.audio_wave.AudioWaveState(
            self.audio_wave.AudioWaveConfig([(10, 20, 30), (200, 100, 50)]),
            clock=FakeClock(100),
        )
        driver = FakeDriver()

        state.render_frame(driver, brightness=123, timing_ms=25)

        self.assertEqual(len(driver.writes), 864)
        self.assertTrue(all(write[1] == (10, 20, 30) for write in driver.writes))
        self.assertTrue(all(write[2] == 123 for write in driver.writes))

    def test_sustained_audio_does_not_retrigger_the_same_drop_every_frame(self):
        clock = FakeClock(100)
        state = self.audio_wave.AudioWaveState(
            self.audio_wave.AudioWaveConfig([(10, 20, 30)]),
            clock=clock,
        )
        bands = (180,) * 8

        self.assertTrue(state.update(1, 180, 180, bands))
        driver = FakeDriver()
        state.render_frame(driver, brightness=255, timing_ms=25)
        radius_after_first_frame = state.wave_snapshot()[0][0]
        self.assertGreater(radius_after_first_frame, 0)

        clock.value += 5
        self.assertTrue(state.update(2, 180, 180, bands))
        self.assertGreater(state.wave_snapshot()[0][0], 0)

    def test_expiry_and_stop_disable_rendering(self):
        clock = FakeClock(100)
        state = self.audio_wave.AudioWaveState(
            self.audio_wave.AudioWaveConfig([(10, 20, 30)]),
            clock=clock,
        )
        state.update(1, 10, 0, (1,) * 8)
        self.assertFalse(state.expired(250))
        self.assertTrue(state.expired(301))

        state.stop()
        driver = FakeDriver()
        state.render_frame(driver, brightness=255, timing_ms=1)
        self.assertTrue(all(write[2] == 0 for write in driver.writes))

    def test_effector_audio_lifecycle_invalidates_and_updates_renderer(self):
        effects = importlib.import_module("effects")
        audio_wave = self.audio_wave
        started = []
        original_start = audio_wave._thread.start_new_thread
        audio_wave._thread.start_new_thread = lambda target, args: started.append((target, args)) or 1
        try:
            driver = FakeDriver()
            effector = effects.Effector(driver)
            effector.start_audio(self.audio_wave.AudioWaveConfig([(1, 2, 3)]))
            self.assertTrue(effector.audio_wave.active)
            self.assertTrue(effector.update_audio((1, 100, 20, (10,) * 8)))
            effector.stop_audio(clear=False)
            self.assertFalse(effector.audio_wave.active)
            self.assertEqual(len(started), 1)
        finally:
            audio_wave._thread.start_new_thread = original_start

    def test_effector_stop_with_clear_clears_driver(self):
        driver = FakeDriver()
        effector = self.audio_wave.AudioWaveEffector(driver)
        original_start = self.audio_wave._thread.start_new_thread
        self.audio_wave._thread.start_new_thread = lambda target, args: 1
        try:
            effector.start(self.audio_wave.AudioWaveConfig([(1, 2, 3)]))
            effector.stop(clear=True)
        finally:
            self.audio_wave._thread.start_new_thread = original_start

        self.assertFalse(effector.active)
        self.assertGreaterEqual(driver.clears, 1)


if __name__ == "__main__":
    unittest.main()
