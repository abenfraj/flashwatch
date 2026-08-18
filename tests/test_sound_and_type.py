# -*- coding: utf-8 -*-
"""The notification voices, and the countdown's face and size.

Both are preferences, and a preference is only worth having if every value it
can take is usable. So neither is checked by picking one and looking at it:

* **every** voice is rendered and measured. What makes these cues bearable on
  the hundredth firing is not the note, it is the envelope -- no corner at the
  onset, no step at the end, nothing above a few kilohertz, and a peak that is
  the same for all of them so switching voice is not also switching volume. A
  preset that got any of that wrong would sound like a click or an alarm, which
  is exactly the thing this table exists to avoid;
* **every** face offered is one this machine actually has, and the size setting
  is checked for the property that makes it safe to shrink: the rows are
  measured through the same font, so a smaller countdown makes a smaller block
  rather than leaving a hole where it used to be.
"""
import sys, io, os, threading, wave

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import _bootstrap  # noqa: F401 -- puts src/ on the import path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import settings as settings_module
tmp = Path(os.environ["TEMP"]) / "flashwatch_sfxtest"
tmp.mkdir(parents=True, exist_ok=True)
settings_module.CONFIG_PATH = tmp / "settings.json"
settings_module.SFX_DIR = tmp / "sfx"

import audio
audio.SFX_DIR = settings_module.SFX_DIR

import overlay
from settings import DEFAULTS, Settings

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


def make_settings(**overrides):
    settings = Settings.__new__(Settings)
    settings._path = None
    settings._lock = threading.RLock()
    settings._data = dict(DEFAULTS)
    settings._data.update(overrides)
    settings.save = lambda: None
    return settings


# ------------------------------------------------------------ the table
check("there are a couple of dozen voices to choose from",
      20 <= len(audio.PRESETS) <= 30, str(len(audio.PRESETS)))
check("their keys are unique",
      len({preset.key for preset in audio.PRESETS}) == len(audio.PRESETS))
check("the default is one of them and is the original chime",
      audio.DEFAULT_PRESET == "chime"
      and DEFAULTS["audio_sfx"] in audio.PRESET_BY_KEY)
check("an unknown name falls back rather than leaving no cue at all",
      audio.preset_for("nope").key == audio.DEFAULT_PRESET
      and audio.preset_for("").key == audio.DEFAULT_PRESET)

# The properties that make a cue soft rather than startling, before a sample is
# rendered. Every one of these is why there is no klaxon in the list.
for preset in audio.PRESETS:
    ok = (preset.engine in audio.ENGINES
          and preset.cutoff <= 6000.0        # nothing shrill survives the filter
          and preset.attack >= 0.004         # no square onset, so no click
          and preset.level <= 0.32           # all at one loudness
          and 0.15 <= preset.ring <= 2.0     # a cue, not a drone
          and preset.warning and preset.ready)
    check(f"{preset.key}: soft by construction", ok,
          f"{preset.engine} cutoff={preset.cutoff} attack={preset.attack} "
          f"ring={preset.ring}")

# The point of the table: genuinely different *mechanisms*, not one voice at
# twenty pitches. An earlier version was exactly that, and it sounded it.
engines = {preset.engine for preset in audio.PRESETS}
check("every engine is actually used by something",
      engines == set(audio.ENGINES), str(sorted(engines)))
check("no engine carries the whole list on its own",
      max(sum(1 for p in audio.PRESETS if p.engine == engine)
          for engine in engines) <= len(audio.PRESETS) // 2,
      str({e: sum(1 for p in audio.PRESETS if p.engine == e) for e in engines}))
# ...and different gestures, which the ear separates more sharply than timbre
# does: a double knock and a rising arpeggio are not the same message.
check("the gestures vary too, not just the voices",
      len({preset.ready for preset in audio.PRESETS}) >= 5,
      str(len({preset.ready for preset in audio.PRESETS})))


# ------------------------------------------------------- what comes out
settings = make_settings()
notifier = audio.Notifier(settings)
rendered = {}

for preset in audio.PRESETS:
    settings.set("audio_sfx", preset.key)
    notifier.refresh()
    for kind, path in (("warning", notifier._warning), ("ready", notifier._ready)):
        if not path.exists():
            check(f"{preset.key}/{kind}: written", False, "missing")
            continue
        with wave.open(str(path)) as handle:
            frames = handle.getnframes()
            fmt = (handle.getnchannels(), handle.getsampwidth(),
                   handle.getframerate())
            raw = handle.readframes(frames)
        rendered[(preset.key, kind)] = raw
        samples = [int.from_bytes(raw[i:i + 2], "little", signed=True)
                   for i in range(0, len(raw), 2)]
        seconds = frames / audio.SAMPLE_RATE
        peak = max(abs(value) for value in samples)
        target = int(preset.level * 32767)
        ok = (fmt == (1, 2, audio.SAMPLE_RATE)
              # Normalised to the preset's own level, so choosing a voice is
              # never also choosing a volume.
              and abs(peak - target) <= 400
              # Long enough to be heard, short enough not to be a drone. The
              # floor is low because a tap really is a tap.
              and 0.20 <= seconds <= 4.0
              # No click at either end: silence in, silence out.
              and abs(samples[0]) < 200 and abs(samples[-1]) < 200)
        check(f"{preset.key}/{kind}: a clean, level cue", ok,
              f"{fmt} peak={peak}/{target} {seconds:.2f}s "
              f"ends={samples[0]},{samples[-1]}")

check("no two voices render the same sound",
      len({bytes(data) for data in rendered.values()}) == len(rendered),
      f"{len(rendered)} cues")


# ------------------------------------------- and different in what way?
# Distinct bytes is a low bar: the first version of this table cleared it easily
# while sounding like one instrument at twenty pitches, which is what it was.
# These two measurements are the ones that would have caught that.
def samples_of(key, kind):
    raw = rendered[(key, kind)]
    return [int.from_bytes(raw[i:i + 2], "little", signed=True)
            for i in range(0, len(raw), 2)]


def brightness(values):
    """Zero crossings per second: a cheap stand-in for how high it sits."""
    crossings = sum(1 for i in range(1, len(values))
                    if (values[i - 1] < 0) != (values[i] < 0))
    return crossings / 2 / (len(values) / audio.SAMPLE_RATE)


def tonality(values):
    """How periodic the waveform is: ~1 for a note, near 0 for noise."""
    start = len(values) // 6
    window = values[start:start + 4000]
    energy = sum(value * value for value in window) / 4 or 1
    return max((sum(window[i] * window[i + lag] for i in range(0, len(window) - lag, 4))
                / energy for lag in range(20, 300, 3)), default=0.0)


bright = {preset.key: brightness(samples_of(preset.key, "ready"))
          for preset in audio.PRESETS}
check("the voices are spread across the range, not clustered at one pitch",
      max(bright.values()) > min(bright.values()) * 6,
      f"{min(bright.values()):.0f}..{max(bright.values()):.0f} Hz")

# The sharpest divide in the table, and the one no amount of re-tuning partials
# could have produced: filtered noise has no pitch to speak of, a struck or blown
# note is periodic. Measured on a few of each rather than on all twenty-two,
# because the autocorrelation is the slow part of this file.
noisy = [tonality(samples_of(key, "ready"))
         for key in ("breath", "brush", "shaker")]
tonal = [tonality(samples_of(key, "ready"))
         for key in ("chime", "fmbell", "pad")]
check("the noise voices really are noise, and the notes really are notes",
      max(noisy) < 0.5 < min(tonal),
      f"noise {max(noisy):.2f} vs tone {min(tonal):.2f}")

# Only the chosen voice is kept on disk: twenty-two of them is megabytes of WAV
# cached for a choice made once, and rendering a pair back takes a tenth of a
# second.
on_disk = sorted(path.name for path in settings_module.SFX_DIR.glob("*.wav"))
check("only the chosen voice stays cached", len(on_disk) == 2, str(on_disk))

# The cues obey the switches; the audition deliberately does not.
played = []
notifier._play = lambda path: played.append(path.name)
settings.set("audio_enabled", False)
notifier.warning()
notifier.ready()
check("switched off, nothing is played", not played, str(played))
notifier.preview()
check("...but the audition still answers", len(played) == 1, str(played))
settings.set("audio_enabled", True)
settings.set("audio_on_ready", False)
played.clear()
notifier.warning()
notifier.ready()
check("the ready cue has its own switch", len(played) == 1, str(played))


# ---------------------------------------------------------- the face
from PySide6.QtGui import QFontDatabase                     # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
faces = overlay.available_countdown_faces()
installed = set(QFontDatabase.families())
check("every face offered is one this machine has",
      all(family in installed for family, _f, _w in faces), str(faces[:3]))
check("and each carries a size multiplier, so one size setting means one thing",
      all(0.9 <= factor <= 1.4 for _n, factor, _w in faces))

BIG = 40.0            # well clear of the legibility floor, so scaling is visible
overlay.set_countdown_style(overlay.FACE_AUTO, 1.0)
full = overlay.countdown_font(BIG).pointSizeF()
overlay.set_countdown_style(overlay.FACE_AUTO, 0.5)
half = overlay.countdown_font(BIG).pointSizeF()
check("halving the size setting halves the countdown",
      abs(half * 2 - full) < 0.01, f"{full:.1f} -> {half:.1f}")
check("and half is what a fresh install gets",
      DEFAULTS["timer_font_scale"] == 0.5)

overlay.set_countdown_style("Consolas", 1.0)
check("a named face is used", overlay.countdown_font(BIG).family() == "Consolas",
      overlay.countdown_font(BIG).family())
overlay.set_countdown_style("Not A Real Font", 1.0)
chosen = overlay.countdown_font(BIG).family()
check("a face this machine does not have falls back to a legible one",
      chosen != "Not A Real Font", chosen)

overlay.set_countdown_style(overlay.FACE_AUTO, 3.0)
ceiling = overlay.countdown_font(BIG).pointSizeF()
overlay.set_countdown_style(overlay.FACE_AUTO, 9.0)
check("the size is clamped, so a hand-edited settings file cannot fill the "
      "screen with one number",
      abs(overlay.countdown_font(BIG).pointSizeF() - ceiling) < 0.01,
      f"{ceiling:.1f} vs {overlay.countdown_font(BIG).pointSizeF():.1f}")
overlay.set_countdown_style(overlay.FACE_AUTO, "not a number")
check("and a nonsense size is ignored rather than raising",
      overlay.countdown_font(BIG).pointSizeF() > 0)

# The property that makes shrinking safe: rows are measured through this font, so
# a smaller countdown produces a smaller block instead of a hole where it was.
from PySide6.QtGui import QFontMetrics                       # noqa: E402

overlay.set_countdown_style(overlay.FACE_AUTO, 1.0)
tall = QFontMetrics(overlay.countdown_font(12.0)).height()
overlay.set_countdown_style(overlay.FACE_AUTO, 0.5)
short = QFontMetrics(overlay.countdown_font(12.0)).height()
check("a smaller countdown measures smaller, so the row shrinks with it",
      short < tall, f"{tall}px -> {short}px")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
