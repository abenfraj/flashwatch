"""Audio notifications.

Cues are synthesised into small WAV files on demand and played through winsound
asynchronously, so no audio dependency is needed, nothing has to be packaged,
and playback never blocks the capture loop or the UI.

**Six ways of making a sound, not one voice at twenty pitches.** An earlier
version of this table was a single additive engine -- a fundamental plus partials
that decayed -- with the ratios and the note changed between presets. That is not
a choice of sound; it is the same instrument played higher or slower, and it read
as exactly that. What actually separates one cue from another is the *mechanism*:

* ``struck``   -- decaying partials. A bar, a string, a bell: the original.
* ``fm``       -- one sine bending another. Reaches metallic and reedy timbres
                  that no reasonable stack of partials gets to.
* ``noise``    -- filtered noise. A breath, a brush, a shaker. No pitch at all,
                  which is as far from a chime as this file goes.
* ``glide``    -- a tone that slides while it sounds. Movement, not a note.
* ``modulated``-- a tone wavering in level or in pitch. A purr, a wobble.
* ``swell``    -- a slow fade in and out rather than a strike. A pad.

On top of that, the *gesture*: one note, two, three, a chord, a repeated tap. A
double knock and a rising arpeggio differ more to the ear than any two timbres
do, so the patterns carry as much of the variety as the engines.

What every one of them still shares is what makes a cue bearable on the hundredth
firing in an evening: a smooth onset, a smooth tail, nothing shrill left after the
low-pass, and one peak level across the whole table so choosing a voice is never
also choosing a volume. Nothing here is a voice line, a meme or a klaxon.

Each preset is one recipe used twice: a shorter gesture for "nearly back", a
fuller and generally rising one for "back up". Rising is the point -- a cooldown
returning is good news, and everyone reads a rise that way without being told.
"""

from __future__ import annotations

import logging
import math
import struct
import wave
from dataclasses import dataclass
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
SFX_VERSION = 4

PEAK_LEVEL = 0.30

# --------------------------------------------------------------------------
# Gestures. Each note is ``(pitch ratio, when it starts, how long it rings)``,
# the last two as multiples of the preset's own ring, so one pattern fits a
# half-second tap and a two-second bowl without being written twice.
# --------------------------------------------------------------------------
Note = tuple[float, float, float]

SINGLE: tuple[Note, ...] = ((1.00, 0.00, 1.00),)
RISE: tuple[Note, ...] = ((1.00, 0.00, 1.00), (1.50, 0.18, 1.00))
OCTAVE: tuple[Note, ...] = ((1.00, 0.00, 1.00), (2.00, 0.18, 1.00))
THIRD: tuple[Note, ...] = ((1.00, 0.00, 1.00), (1.25, 0.16, 1.00))
UP3: tuple[Note, ...] = ((1.00, 0.00, 0.70), (1.25, 0.14, 0.70),
                         (1.50, 0.28, 1.00))
DOWN3: tuple[Note, ...] = ((1.50, 0.00, 0.70), (1.25, 0.14, 0.70),
                           (1.00, 0.28, 1.00))
CHORD: tuple[Note, ...] = ((1.00, 0.00, 1.00), (1.25, 0.00, 1.00),
                           (1.50, 0.00, 1.00))
TAP2: tuple[Note, ...] = ((1.00, 0.00, 1.00), (1.00, 0.42, 1.00))
TAP3: tuple[Note, ...] = ((1.00, 0.00, 1.00), (1.00, 0.38, 1.00),
                          (1.00, 0.76, 1.00))
STEP2: tuple[Note, ...] = ((1.00, 0.00, 1.00), (1.50, 0.42, 1.00))
STEP3: tuple[Note, ...] = ((1.00, 0.00, 1.00), (1.25, 0.34, 1.00),
                           (1.50, 0.68, 1.00))

# The original voice, and still the default timbre for ``struck``.
CHIME_PARTIALS = (
    (1.00, 1.000, 1.0),
    (2.00, 0.260, 1.9),
    (3.00, 0.080, 3.0),
    (4.02, 0.035, 4.2),
)


@dataclass(frozen=True)
class Preset:
    """One way of making a sound, and the two things it says with it.

    Most fields belong to one engine and are ignored by the others; that is what
    a synth patch is. ``partials`` is ``(ratio to the fundamental, amplitude, how
    much faster it decays)`` -- ratios near whole numbers sound like a bar or a
    string, ratios deliberately off them like metal.
    """

    key: str
    engine: str                       # struck | fm | noise | glide | modulated | swell
    root: float                       # Hz
    ring: float                       # seconds one note lasts
    warning: tuple[Note, ...] = SINGLE
    ready: tuple[Note, ...] = RISE
    cutoff: float = 2600.0            # low-pass, takes the glare off the top
    attack: float = 0.022             # seconds; longer reads as blown, not struck
    level: float = PEAK_LEVEL

    # struck / swell
    partials: tuple[tuple[float, float, float], ...] = CHIME_PARTIALS
    # fm: modulator frequency as a ratio of the carrier, how deep it bends it,
    # and how much faster that depth falls away than the note does. A depth that
    # decays is the whole trick -- it is what makes an FM note start bright and
    # settle, the way a struck thing does.
    fm_ratio: float = 1.41
    fm_index: float = 3.0
    fm_decay: float = 2.5
    # noise: where the band sits, as a ratio of the note, and how narrow it is.
    # A wide band is a breath, a narrow one is nearly a pitch.
    noise_q: float = 2.0
    noise_ratio: float = 1.0
    # glide: where the note ends up, as a ratio of where it started.
    glide: float = 1.0
    # modulated: tremolo depth (0-1) and rate, or vibrato depth in cents.
    tremolo: float = 0.0
    tremolo_hz: float = 9.0
    vibrato_cents: float = 0.0
    vibrato_hz: float = 5.5

    def voices(self, pattern: tuple[Note, ...]) -> list[tuple[float, float, float]]:
        """A gesture resolved to ``(frequency, start seconds, ring seconds)``."""
        return [(self.root * ratio, start * self.ring, length * self.ring)
                for ratio, start, length in pattern]


# --------------------------------------------------------------------------
# Twenty-two voices, grouped by how they are made. Ordered so that auditioning
# them top to bottom walks through the families rather than shuffling them.
# --------------------------------------------------------------------------
PRESETS: tuple[Preset, ...] = (
    # -- struck: decaying partials ---------------------------------------
    # The original, first and unchanged: somebody who liked it has to be able to
    # keep it.
    Preset("chime", "struck", 587.33, 0.85),
    Preset("bell", "struck", 523.25, 1.15, SINGLE, OCTAVE,
           partials=((1.00, 1.000, 1.0), (2.00, 0.320, 1.6),
                     (2.76, 0.170, 2.2), (5.40, 0.050, 3.6)), cutoff=2400.0),
    Preset("bowl", "struck", 392.00, 1.90, SINGLE, THIRD,
           partials=((1.00, 1.000, 1.0), (2.40, 0.200, 1.4),
                     (4.60, 0.055, 2.6)), cutoff=1900.0),
    Preset("marimba", "struck", 415.30, 0.55, SINGLE, UP3,
           partials=((1.00, 1.000, 1.0), (4.00, 0.300, 2.6),
                     (10.00, 0.060, 4.0)), cutoff=2000.0),
    Preset("harp", "struck", 523.25, 0.90, THIRD, CHORD,
           partials=((1.00, 1.000, 1.0), (2.00, 0.290, 1.4),
                     (3.00, 0.140, 1.8), (4.00, 0.065, 2.4)), cutoff=2400.0),
    Preset("musicbox", "struck", 880.00, 0.60, STEP2, STEP3,
           partials=((1.00, 1.000, 1.0), (2.00, 0.380, 1.5),
                     (4.05, 0.150, 2.6), (8.10, 0.045, 4.0)), cutoff=3000.0,
           level=0.27),
    # Rhythm rather than melody: the same note, struck twice and three times.
    Preset("knock", "struck", 261.63, 0.26, TAP2, TAP3,
           partials=((1.00, 1.000, 1.0), (2.70, 0.240, 2.4)), cutoff=1500.0,
           attack=0.005),
    Preset("tick", "struck", 1046.50, 0.20, SINGLE, TAP2,
           partials=((1.00, 1.000, 1.0), (2.90, 0.190, 2.4)), cutoff=3000.0,
           attack=0.004, level=0.26),

    # -- fm: one sine bending another ------------------------------------
    Preset("fmbell", "fm", 466.16, 1.30, SINGLE, OCTAVE,
           cutoff=2800.0, fm_ratio=1.41, fm_index=3.4, fm_decay=2.2),
    Preset("glass", "fm", 783.99, 0.85, SINGLE, RISE,
           cutoff=3400.0, fm_ratio=2.76, fm_index=2.2, fm_decay=3.4,
           level=0.27),
    Preset("reed", "fm", 349.23, 0.70, SINGLE, RISE,
           cutoff=2000.0, attack=0.045, fm_ratio=1.00, fm_index=2.4,
           fm_decay=1.4),
    Preset("clave", "fm", 622.25, 0.22, TAP2, TAP3,
           cutoff=2600.0, attack=0.004, fm_ratio=3.00, fm_index=1.6,
           fm_decay=4.0, level=0.26),

    # -- noise: no pitch at all ------------------------------------------
    Preset("breath", "noise", 392.00, 0.90, SINGLE, RISE,
           cutoff=1600.0, attack=0.140, noise_q=1.2, noise_ratio=2.0,
           level=0.28),
    Preset("brush", "noise", 587.33, 0.55, SINGLE, TAP2,
           cutoff=3000.0, attack=0.030, noise_q=0.9, noise_ratio=4.0,
           level=0.26),
    Preset("shaker", "noise", 880.00, 0.16, TAP2, TAP3,
           cutoff=6000.0, attack=0.004, noise_q=1.6, noise_ratio=6.0,
           level=0.22),
    Preset("hush", "noise", 261.63, 1.20, SINGLE, THIRD,
           cutoff=1100.0, attack=0.220, noise_q=3.5, noise_ratio=1.0,
           level=0.28),

    # -- glide: a note that moves ----------------------------------------
    Preset("swoop", "glide", 392.00, 0.55, SINGLE, TAP2,
           cutoff=2200.0, attack=0.030, glide=1.90),
    Preset("droplet", "glide", 1174.66, 0.45, SINGLE, STEP2,
           cutoff=3000.0, attack=0.006, glide=0.42, level=0.27),

    # -- modulated: a tone that wavers -----------------------------------
    Preset("warble", "modulated", 523.25, 0.90, SINGLE, RISE,
           cutoff=2200.0, attack=0.035, tremolo=0.75, tremolo_hz=11.0),
    Preset("vibrato", "modulated", 587.33, 1.00, SINGLE, RISE,
           cutoff=1900.0, attack=0.090, vibrato_cents=45.0, vibrato_hz=5.5),

    # -- swell: faded in and out rather than struck -----------------------
    Preset("pad", "swell", 329.63, 1.40, SINGLE, CHORD,
           cutoff=1500.0,
           partials=((1.00, 1.000, 1.0), (2.00, 0.240, 1.0),
                     (3.00, 0.090, 1.0)), level=0.28),
    Preset("choir", "swell", 440.00, 1.60, THIRD, CHORD,
           cutoff=1800.0,
           partials=((1.00, 1.000, 1.0), (2.00, 0.180, 1.0),
                     (3.00, 0.110, 1.0), (4.00, 0.040, 1.0)),
           vibrato_cents=18.0, vibrato_hz=4.5, level=0.28),
)

PRESET_BY_KEY: dict[str, Preset] = {preset.key: preset for preset in PRESETS}
DEFAULT_PRESET = PRESETS[0].key

ENGINES = ("struck", "fm", "noise", "glide", "modulated", "swell")


def preset_for(key: str) -> Preset:
    """The named preset, falling back to the original rather than failing.

    A settings file written by a newer build -- or edited by hand -- must not be
    able to leave the program with no cue at all.
    """
    return PRESET_BY_KEY.get(str(key or ""), PRESET_BY_KEY[DEFAULT_PRESET])


# --------------------------------------------------------------------------
# Synthesis
# --------------------------------------------------------------------------
def _attack_gain(t: float, attack: float) -> float:
    """Raised cosine onset: no corner, so no audible click."""
    if t >= attack:
        return 1.0
    return 0.5 - 0.5 * math.cos(math.pi * t / attack)


class _Noise:
    """A tiny deterministic white-noise source.

    Deterministic on purpose, and not for taste: the cue is written to a file and
    cached, so a source seeded from the clock would make "the shaker" a different
    sound every time it was regenerated, and the one thing a notification must be
    is the same every time.
    """

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = (seed * 2654435761) & 0xFFFFFFFF

    def __call__(self) -> float:
        # Numerical Recipes' LCG. Cheap, adequately white for a band-pass, and
        # short enough to read.
        self._state = (1664525 * self._state + 1013904223) & 0xFFFFFFFF
        return self._state / 2147483648.0 - 1.0


def _bandpass(samples: list[float], centre: float, q: float) -> None:
    """Constant-skirt band-pass biquad, in place.

    What turns noise into an instrument: the centre decides whether it reads as a
    breath, a brush or a shaker, and Q decides how close to a pitch it gets.
    """
    centre = max(60.0, min(centre, SAMPLE_RATE * 0.45))
    w0 = 2.0 * math.pi * centre / SAMPLE_RATE
    alpha = math.sin(w0) / (2.0 * max(0.3, q))
    b0, b1, b2 = alpha, 0.0, -alpha
    a0, a1, a2 = 1.0 + alpha, -2.0 * math.cos(w0), 1.0 - alpha
    b0, b1, b2 = b0 / a0, b1 / a0, b2 / a0
    a1, a2 = a1 / a0, a2 / a0

    x1 = x2 = y1 = y2 = 0.0
    for index, x0 in enumerate(samples):
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        samples[index] = y0
        x2, x1 = x1, x0
        y2, y1 = y1, y0


def _note(preset: Preset, frequency: float, ring: float,
          seed: int) -> list[float]:
    """One note of one voice, as a buffer starting at zero.

    Every engine ends with the same two properties -- it starts silent and it
    ends silent -- because that, and not the timbre, is what stops a cue from
    clicking.
    """
    count = max(1, int(SAMPLE_RATE * ring))
    # Ring out to roughly -40 dB by the end of the note.
    tau = ring / 4.6
    out = [0.0] * count

    if preset.engine == "noise":
        source = _Noise(seed)
        for index in range(count):
            out[index] = source()
        _bandpass(out, frequency * preset.noise_ratio, preset.noise_q)
        for index in range(count):
            t = index / SAMPLE_RATE
            out[index] *= math.exp(-t / tau) * _attack_gain(t, preset.attack)
        return out

    if preset.engine == "swell":
        # A window rather than a decay: in and out, symmetrically. That shape is
        # the whole difference between a pad and a struck note, and no choice of
        # partials gets there.
        for index in range(count):
            t = index / SAMPLE_RATE
            window = 0.5 - 0.5 * math.cos(2.0 * math.pi * index / count)
            bend = 1.0
            if preset.vibrato_cents:
                bend = 2.0 ** (preset.vibrato_cents / 1200.0
                               * math.sin(2.0 * math.pi * preset.vibrato_hz * t))
            sample = 0.0
            for ratio, amplitude, _decay in preset.partials:
                sample += amplitude * math.sin(
                    2.0 * math.pi * frequency * ratio * bend * t)
            out[index] = sample * window
        return out

    if preset.engine == "fm":
        for index in range(count):
            t = index / SAMPLE_RATE
            envelope = math.exp(-t / tau) * _attack_gain(t, preset.attack)
            # The depth of the bend falls faster than the note does, which is
            # what makes it start bright and settle instead of buzzing evenly.
            depth = preset.fm_index * math.exp(-t / (tau / preset.fm_decay))
            modulator = math.sin(2.0 * math.pi * frequency * preset.fm_ratio * t)
            out[index] = envelope * math.sin(
                2.0 * math.pi * frequency * t + depth * modulator)
        return out

    if preset.engine in ("glide", "modulated"):
        # Phase is accumulated rather than computed from t, because the frequency
        # is not constant: sin(2*pi*f(t)*t) would sweep at twice the intended
        # rate and land an octave out.
        phase = 0.0
        step = 1.0 / SAMPLE_RATE
        for index in range(count):
            t = index * step
            frequency_now = frequency
            if preset.engine == "glide":
                frequency_now *= preset.glide ** (t / ring)
            elif preset.vibrato_cents:
                frequency_now *= 2.0 ** (
                    preset.vibrato_cents / 1200.0
                    * math.sin(2.0 * math.pi * preset.vibrato_hz * t))
            phase += 2.0 * math.pi * frequency_now * step
            envelope = math.exp(-t / tau) * _attack_gain(t, preset.attack)
            if preset.tremolo:
                envelope *= 1.0 - preset.tremolo * (
                    0.5 - 0.5 * math.cos(2.0 * math.pi * preset.tremolo_hz * t))
            out[index] = envelope * (math.sin(phase)
                                     + 0.12 * math.sin(2.0 * phase))
        return out

    # struck
    for index in range(count):
        t = index / SAMPLE_RATE
        gain = _attack_gain(t, preset.attack)
        sample = 0.0
        for ratio, amplitude, decay in preset.partials:
            sample += amplitude * math.exp(-t / (tau / decay)) \
                * math.sin(2.0 * math.pi * frequency * ratio * t)
        out[index] = sample * gain
    return out


def _render(preset: Preset, pattern: tuple[Note, ...]) -> list[float]:
    """Mix a gesture's notes into one buffer.

    Notes overlap freely, so a chord is a chord and a two-note rise blends into
    one sound rather than landing as two hits.
    """
    voices = preset.voices(pattern)
    total = max(start + ring for _f, start, ring in voices)
    length = int(SAMPLE_RATE * (total + 0.05))
    buffer = [0.0] * length

    for seed, (frequency, start, ring) in enumerate(voices, start=1):
        offset = int(SAMPLE_RATE * start)
        # A seed per note, so two taps of a shaker are not the identical
        # waveform twice -- which sounds like an echo rather than a repeat.
        note = _note(preset, frequency, ring, seed)
        for index in range(min(len(note), length - offset)):
            buffer[offset + index] += note[index]
    return buffer


def _soften(buffer: list[float], cutoff_hz: float) -> None:
    """One-pole low-pass, in place: takes the glare off the upper partials."""
    alpha = 1.0 / (1.0 + SAMPLE_RATE / (2 * math.pi * cutoff_hz))
    previous = 0.0
    for index, sample in enumerate(buffer):
        previous += alpha * (sample - previous)
        buffer[index] = previous


def _write_cue(path: Path, preset: Preset, pattern: tuple[Note, ...]) -> None:
    """Write one cue as a WAV, normalised to the preset's level."""
    buffer = _render(preset, pattern)
    _soften(buffer, preset.cutoff)

    # Fade both ends *before* normalising, and that order is the whole of it. A
    # short cue's peak lands inside the head fade, so scaling first and fading
    # afterwards quietly halves the loudest thing in the file -- which is how a
    # tick came out at half the level of a bowl while both claimed the same one.
    #
    # The tail fade stops a truncated ring leaving a step at the last sample. The
    # head fade is for the noise voices only: their band-pass rings from its own
    # initial state, a click the note's attack ramp cannot see. Four milliseconds
    # is enough for that and short enough to leave a struck onset alone.
    tail = int(SAMPLE_RATE * 0.03)
    head = int(SAMPLE_RATE * 0.004)
    for index in range(len(buffer)):
        remaining = len(buffer) - index
        if remaining < tail:
            buffer[index] *= remaining / tail
        if index < head:
            buffer[index] *= index / head

    peak = max((abs(sample) for sample in buffer), default=0.0)
    scale = (preset.level / peak) if peak else 0.0

    frames = bytearray()
    for sample in buffer:
        value = max(-1.0, min(1.0, sample * scale))
        frames += struct.pack("<h", int(value * 32767))

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(frames))


class Notifier:
    """Plays the warning and ready cues, in whichever voice is chosen."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.preset = preset_for(settings.get("audio_sfx", DEFAULT_PRESET))
        self._warning = Path()
        self._ready = Path()
        self._sync_paths()
        self._ensure_sounds()

    # ------------------------------------------------------------------
    def _sync_paths(self) -> None:
        self._warning = SFX_DIR / f"{self.preset.key}-warning-v{SFX_VERSION}.wav"
        self._ready = SFX_DIR / f"{self.preset.key}-ready-v{SFX_VERSION}.wav"

    def refresh(self) -> bool:
        """Follow a change of voice in the settings. Returns True if it changed.

        Rendering a cue takes a tenth of a second, so this is cheap enough to run
        on the settings window's own thread -- and it has to be synchronous,
        because the button that auditions a voice is pressed in the same breath
        as choosing it.
        """
        chosen = preset_for(self.settings.get("audio_sfx", DEFAULT_PRESET))
        if chosen.key == self.preset.key:
            return False
        self.preset = chosen
        self._sync_paths()
        self._ensure_sounds()
        log.info("notification voice: %s (%s)", chosen.key, chosen.engine)
        return True

    def _ensure_sounds(self) -> None:
        try:
            self._drop_stale()
            if not self._warning.exists():
                _write_cue(self._warning, self.preset, self.preset.warning)
            if not self._ready.exists():
                _write_cue(self._ready, self.preset, self.preset.ready)
        except OSError as exc:
            log.warning("could not create notification sounds (%s)", exc)

    def _drop_stale(self) -> None:
        """Remove cues from older builds, and from voices no longer chosen.

        The whole set is not kept on disk. Twenty-two voices is megabytes of WAV
        to cache for a choice that is made once, and rendering the pair back
        takes a tenth of a second.
        """
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

    def preview(self) -> None:
        """Play the "back up" cue on demand, whatever the settings say.

        Deliberately ignores ``audio_enabled``: this is the button that answers
        "what does this one sound like?", and refusing to answer because the cues
        are currently switched off would be a puzzle rather than a safeguard.
        """
        self.refresh()
        self._play(self._ready)
