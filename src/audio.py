"""Audio notifications.

Tones are synthesised into small WAV files on first run and played through
winsound asynchronously, so no audio dependency is needed and playback never
blocks the capture loop or the UI.
"""

from __future__ import annotations

import logging
import math
import struct
import wave
from pathlib import Path

from settings import SFX_DIR

log = logging.getLogger(__name__)

try:
    import winsound
    HAVE_WINSOUND = True
except ImportError:                                   # pragma: no cover
    HAVE_WINSOUND = False

SAMPLE_RATE = 22050


def _write_tone(path: Path, segments: list[tuple[float, float]],
                volume: float = 0.35) -> None:
    """Write a WAV of ``(frequency_hz, duration_s)`` segments."""
    frames = bytearray()
    for frequency, duration in segments:
        count = int(SAMPLE_RATE * duration)
        for index in range(count):
            t = index / SAMPLE_RATE
            # Short linear fades stop the clicks you get from truncating a sine.
            fade = min(1.0, min(index, count - index) / (SAMPLE_RATE * 0.012))
            sample = math.sin(2 * math.pi * frequency * t) * volume * fade
            frames += struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 32767))

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(frames))


class Notifier:
    """Plays the warning and ready cues."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self._warning = SFX_DIR / "warning.wav"
        self._ready = SFX_DIR / "ready.wav"
        self._ensure_sounds()

    def _ensure_sounds(self) -> None:
        try:
            if not self._warning.exists():
                _write_tone(self._warning, [(760.0, 0.09), (0.0, 0.04),
                                            (760.0, 0.09)])
            if not self._ready.exists():
                _write_tone(self._ready, [(660.0, 0.10), (990.0, 0.16)])
        except OSError as exc:
            log.warning("could not create notification sounds (%s)", exc)

    def _play(self, path: Path) -> None:
        if not HAVE_WINSOUND or not path.exists():
            return
        try:
            winsound.PlaySound(str(path),
                               winsound.SND_FILENAME | winsound.SND_ASYNC)
        except RuntimeError as exc:
            log.debug("could not play %s (%s)", path, exc)

    def warning(self) -> None:
        if self.settings.get("audio_enabled"):
            self._play(self._warning)

    def ready(self) -> None:
        if self.settings.get("audio_enabled") and self.settings.get("audio_on_ready"):
            self._play(self._ready)
