"""Audio notifications.

Cues are synthesised into small WAV files on first run and played through
winsound asynchronously, so no audio dependency is needed and playback never
blocks the capture loop or the UI.

The voices are soft mallet/chime tones rather than beeps: a gentle attack, an
exponential ring-out, and harmonics that fade faster than the fundamental.
That carries over a fight without the startle of a square-edged alarm.
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

# Bumped whenever the cues are re-voiced, so cached WAVs from an older build
# are replaced instead of quietly outliving the change.
SFX_VERSION = 2

ATTACK_SECONDS = 0.022
PEAK_LEVEL = 0.30

# (ratio to the fundamental, amplitude, how much faster it decays). The mild
# inharmonicity on the top partial is what reads as "struck" instead of "sine".
_PARTIALS = (
    (1.00, 1.000, 1.0),
    (2.00, 0.260, 1.9),
    (3.00, 0.080, 3.0),
    (4.02, 0.035, 4.2),
)


def _render(voices: list[tuple[float, float, float]]) -> list[float]:
    """Mix ``(frequency_hz, start_s, ring_s)`` voices into one buffer.

    Voices overlap freely, so a two-note cue blends into a single chime
    instead of two separate hits.
    """
    total = max(start + ring for _, start, ring in voices)
    length = int(SAMPLE_RATE * (total + 0.05))
    buffer = [0.0] * length

    for frequency, start, ring in voices:
        offset = int(SAMPLE_RATE * start)
        count = min(int(SAMPLE_RATE * ring), length - offset)
        # Ring out to roughly -40 dB by the end of the note.
        tau = ring / 4.6
        for index in range(count):
            t = index / SAMPLE_RATE
            attack = min(1.0, t / ATTACK_SECONDS)
            # Raised cosine: no corner at the onset, so no audible click.
            attack = 0.5 - 0.5 * math.cos(math.pi * attack)
            sample = 0.0
            for ratio, amplitude, decay in _PARTIALS:
                sample += amplitude * math.exp(-t / (tau / decay)) \
                    * math.sin(2 * math.pi * frequency * ratio * t)
            buffer[offset + index] += sample * attack

    return buffer


def _soften(buffer: list[float], cutoff_hz: float = 2600.0) -> None:
    """One-pole low-pass, in place: takes the glare off the upper partials."""
    alpha = 1.0 / (1.0 + SAMPLE_RATE / (2 * math.pi * cutoff_hz))
    previous = 0.0
    for index, sample in enumerate(buffer):
        previous += alpha * (sample - previous)
        buffer[index] = previous


def _write_chime(path: Path, voices: list[tuple[float, float, float]],
                 level: float = PEAK_LEVEL) -> None:
    """Write a WAV of overlapping mallet voices, normalised to ``level``."""
    buffer = _render(voices)
    _soften(buffer)

    peak = max((abs(sample) for sample in buffer), default=0.0)
    scale = (level / peak) if peak else 0.0
    # Fade the tail so normalisation cannot leave a step at the very end.
    fade = int(SAMPLE_RATE * 0.03)

    frames = bytearray()
    for index, sample in enumerate(buffer):
        remaining = len(buffer) - index
        if remaining < fade:
            sample *= remaining / fade
        value = max(-1.0, min(1.0, sample * scale))
        frames += struct.pack("<h", int(value * 32767))

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
        self._warning = SFX_DIR / f"warning-v{SFX_VERSION}.wav"
        self._ready = SFX_DIR / f"ready-v{SFX_VERSION}.wav"
        self._ensure_sounds()

    def _ensure_sounds(self) -> None:
        try:
            self._drop_stale()
            if not self._warning.exists():
                # A single soft D5, left to ring: a nudge, not an alarm.
                _write_chime(self._warning, [(587.33, 0.0, 0.85)])
            if not self._ready.exists():
                # A4 into E5, a fifth apart and overlapping, so it lands as
                # one resolved chime.
                _write_chime(self._ready, [(440.00, 0.0, 1.15),
                                           (659.25, 0.17, 1.15)])
        except OSError as exc:
            log.warning("could not create notification sounds (%s)", exc)

    def _drop_stale(self) -> None:
        """Remove cues from older builds so the cache does not accumulate."""
        keep = {self._warning.name, self._ready.name}
        for stale in SFX_DIR.glob("*.wav"):
            if stale.name not in keep:
                try:
                    stale.unlink()
                except OSError as exc:                 # pragma: no cover
                    log.debug("could not remove %s (%s)", stale, exc)

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
