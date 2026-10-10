from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class AudioFrame:
    frame_seq: int
    bands: tuple[int, ...]
    energy: int
    beat: int

    def __post_init__(self) -> None:
        if not 0 <= int(self.frame_seq) <= 0xFFFF:
            raise ValueError("frame_seq must fit in two bytes")
        if len(self.bands) != 8 or any(not 0 <= int(value) <= 0xFF for value in self.bands):
            raise ValueError("bands must contain eight bytes")
        if not 0 <= int(self.energy) <= 0xFF:
            raise ValueError("energy must fit in one byte")
        if not 0 <= int(self.beat) <= 0xFF:
            raise ValueError("beat must fit in one byte")


class SpectrumAnalyzer:
    def __init__(
        self,
        sample_rate: int = 48000,
        fft_size: int = 1024,
        hop_size: int = 512,
        band_count: int = 8,
    ) -> None:
        if sample_rate <= 0 or fft_size <= 0 or hop_size <= 0:
            raise ValueError("sample_rate, fft_size, and hop_size must be positive")
        if band_count != 8:
            raise ValueError("the audio protocol currently requires eight bands")
        self.sample_rate = int(sample_rate)
        self.fft_size = int(fft_size)
        self.hop_size = int(hop_size)
        self.band_count = int(band_count)
        self._window = np.hanning(self.fft_size).astype(np.float32)
        self._frequencies = np.fft.rfftfreq(self.fft_size, 1.0 / self.sample_rate)
        self._band_edges = np.geomspace(60.0, 8000.0, self.band_count + 1)
        self._band_masks = tuple(
            (self._frequencies >= self._band_edges[index])
            & (self._frequencies < self._band_edges[index + 1])
            for index in range(self.band_count)
        )
        self._publish_interval = max(self.hop_size, self.sample_rate // 30)
        self._buffer = np.empty(0, dtype=np.float32)
        self._buffer_start = 0
        self._last_emitted_start: int | None = None
        self._frame_seq = 0
        self._smoothed = np.zeros(self.band_count, dtype=np.float32)
        self._low_baseline = 0.0

    def reset(self) -> None:
        self._buffer = np.empty(0, dtype=np.float32)
        self._buffer_start = 0
        self._last_emitted_start = None
        self._frame_seq = 0
        self._smoothed.fill(0)
        self._low_baseline = 0.0

    def process(self, samples: Sequence[float]) -> list[AudioFrame]:
        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        if values.size:
            self._buffer = np.concatenate((self._buffer, values))

        frames: list[AudioFrame] = []
        while self._buffer.size >= self.fft_size:
            window_start = self._buffer_start
            window = self._buffer[: self.fft_size] * self._window
            if self._last_emitted_start is None or window_start - self._last_emitted_start >= self._publish_interval:
                frames.append(self._analyze_window(window))
                self._last_emitted_start = window_start
            self._buffer = self._buffer[self.hop_size :]
            self._buffer_start += self.hop_size
        return frames

    def _analyze_window(self, window: np.ndarray) -> AudioFrame:
        spectrum = np.abs(np.fft.rfft(window)) * (2.0 / self.fft_size)
        raw_levels = np.asarray(
            [float(np.max(spectrum[mask])) if np.any(mask) else 0.0 for mask in self._band_masks],
            dtype=np.float32,
        )
        normalized = np.clip(np.log1p(raw_levels * 20.0) / np.log1p(20.0) * 255.0, 0.0, 255.0)
        attack = normalized > self._smoothed
        self._smoothed = np.where(
            attack,
            self._smoothed + (normalized - self._smoothed) * 0.65,
            self._smoothed + (normalized - self._smoothed) * 0.20,
        )

        low_level = float(np.mean(self._smoothed[:2]))
        beat = int(np.clip(max(0.0, low_level - self._low_baseline) * 2.5, 0.0, 255.0))
        self._low_baseline = self._low_baseline * 0.94 + low_level * 0.06

        rms = float(np.sqrt(np.mean(np.square(window))))
        energy = int(np.clip(rms * 360.0, 0.0, 255.0))
        bands = tuple(int(np.clip(round(value), 0, 255)) for value in self._smoothed)
        frame = AudioFrame(self._frame_seq, bands, energy, beat)
        self._frame_seq = (self._frame_seq + 1) & 0xFFFF
        return frame
