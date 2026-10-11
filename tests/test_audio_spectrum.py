import unittest

import numpy as np

from client.audio_spectrum import AudioFrame, SpectrumAnalyzer


def tone(frequency: float, samples: int = 1024, sample_rate: int = 48000) -> np.ndarray:
    indexes = np.arange(samples, dtype=np.float32)
    return np.sin(2 * np.pi * frequency * indexes / sample_rate)


class AudioSpectrumTests(unittest.TestCase):
    def test_silence_produces_zeroed_frame(self):
        analyzer = SpectrumAnalyzer()

        frames = analyzer.process(np.zeros(1024, dtype=np.float32))

        self.assertEqual(len(frames), 1)
        self.assertIsInstance(frames[0], AudioFrame)
        self.assertEqual(frames[0].bands, (0,) * 8)
        self.assertEqual(frames[0].energy, 0)
        self.assertEqual(frames[0].beat, 0)

    def test_low_frequency_tone_concentrates_in_low_bands(self):
        frame = SpectrumAnalyzer().process(tone(120))[0]

        self.assertGreater(sum(frame.bands[:2]), sum(frame.bands[4:]))

    def test_high_frequency_tone_concentrates_in_high_bands(self):
        frame = SpectrumAnalyzer().process(tone(6000))[0]

        self.assertGreater(sum(frame.bands[5:]), sum(frame.bands[:3]))

    def test_wire_values_are_clamped(self):
        frame = SpectrumAnalyzer().process(np.full(1024, 10.0, dtype=np.float32))[0]

        self.assertTrue(all(0 <= value <= 255 for value in frame.bands))
        self.assertIn(frame.energy, range(256))
        self.assertIn(frame.beat, range(256))

    def test_short_input_is_buffered_until_fft_window_is_full(self):
        analyzer = SpectrumAnalyzer()

        self.assertEqual(analyzer.process(np.zeros(512, dtype=np.float32)), [])
        self.assertEqual(len(analyzer.process(np.zeros(512, dtype=np.float32))), 1)

    def test_frame_sequence_wraps_at_ffff(self):
        analyzer = SpectrumAnalyzer()
        analyzer._frame_seq = 0xFFFF

        first = analyzer.process(np.zeros(1024, dtype=np.float32))[0]
        second = analyzer.process(np.zeros(2048, dtype=np.float32))[0]

        self.assertEqual(first.frame_seq, 0xFFFF)
        self.assertEqual(second.frame_seq, 0x0000)

    def test_reset_keeps_frame_sequence_monotonic_across_capture_sessions(self):
        analyzer = SpectrumAnalyzer()

        first = analyzer.process(np.zeros(1024, dtype=np.float32))[0]
        analyzer.reset()
        second = analyzer.process(np.zeros(1024, dtype=np.float32))[0]

        self.assertEqual(second.frame_seq, (first.frame_seq + 1) & 0xFFFF)


if __name__ == "__main__":
    unittest.main()
