# Flashwatch

Overlay that tracks enemy summoner spell and ultimate cooldowns by reading the
in-game chat with OCR. No key presses needed during a game.

## How it stays safe

The application only ever looks at pixels on your screen, the same information
you can see yourself. It does **not** inject into League, read its memory, touch
its files, or send any input. The only network traffic is to Riot's public Data
Dragon CDN, for champion names, spell names, cooldowns and icons.

## Why it is reliable

It keys on the game's own announcement, not on what players type. In a real game
that announcement is the cast line, and League prints it **for enemies only** — it
never narrates your own team:

```
(12:04) Darius a utilisé Saut éclair
│       │                └─ the spell
│       └─ the champion, an enemy by construction
└─ the game clock
```

An English client says `Darius used Flash` or `Darius has used Flash`; both are
matched, as is the French wording, whichever data locale is loaded.

The cooldown itself comes from the game's table (Flash: 300 s, or 246 s with
Cosmic Insight, which is assumed by default). The clock is what makes reading the
line *late* cost nothing: the app compares the line's timestamp against where it
already believes the game clock to be and back-dates the timer by the difference.

A second form is also accepted, and states the remaining time outright:

```
Ayoub (Lux): Attendez Ahri Saut éclair - 245 sec.
└─ author ──┘ └wait┘ └target┘└─ spell ─┘  └remaining┘
```

**This one is a test aid, not a real-game message.** Typing it in chat is the
quickest way to prove the OCR is reading your chat area at all: it carries a
number, so the resulting timer is unambiguous. When such a number is present it is
authoritative — nothing about rank or haste is guessed, so an ultimate timed this
way is exact too — and the timer is anchored on an absolute deadline
(`ready_at = timestamp + stated_seconds`) so repeats of the same line agree
instead of fighting.

> This correction needs a game clock. Either source works: the `(mm:ss)` timestamp
> prefixing chat lines, or — better, because the player can switch timestamps off —
> the match timer itself, once its area is placed in test mode (see *Three areas,
> same frame*). Without any clock the timer is anchored when the line is read
> instead, accurate to roughly a second in the steady state but losing whatever
> the detection delay was. **Settings → Statut → "Horloge estimée"** shows `-` when
> no clock is being read.

**Once set, a timer is left alone.** Everything that could move a running
countdown is refused rather than trusted, because a wrong number presented as fact
is worse than a missing one:

| A line saying… | …while a timer runs |
| --- | --- |
| the same or less time (the line re-read, or scrollback revealing an older one) | ignored |
| materially more time (15 s+) | treated as a recast, timer restarts |
| a cooldown recomputed from a base value over one whose seconds were *stated* | ignored — a stated number outranks any estimate |
| nothing left of the cooldown (read far too late) | ignored; it can no longer delete the entry |

The same caution applies to clearing the board. A game ending is read from the game
*process*, not from the window answering: alt-tab, a loading screen or one unlucky
window enumeration used to look like "the game ended", wiping every timer and then
starting a "new" session on the next poll. And a chat line whose clock reads
suspiciously early — `10:45` misread as `0:45` — now needs a second line to agree
before it counts as a new game.

The two forms are trusted differently, and the difference is the author prefix.
`Attendez … - N sec.` is self-verifying — the trailing count is not something that
appears by accident — so it is accepted whether or not a name precedes it, which is
what lets you type it yourself as a test. The bare `a utilisé` / `used` wording has
nothing to check against and a teammate could plausibly type those words, so it is
only trusted **unattributed**, exactly as the game prints it. Ordinary chat, pings
and emotes fall through and are discarded.

## Setup

Requires Python 3.11 (see *Known constraints*).

```bash
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Then launch:

```bash
run.bat
```

First run downloads champion/spell data and ~350 icons (about 9 MB) and caches
them under `assets/cache/`. Later runs are offline and instant.

The app lives in the system tray (the notification area of the taskbar).
Double-click the tray icon for settings.

**To close it**, any of:

- right-click the tray icon → **Quitter (fermer le programme)**
- the settings window's **X**, or right-click its taskbar button → Close
- the **Quitter** button at the bottom of the settings window

Use **Masquer** instead if you want it to keep running in the tray. Starting it
twice is not a problem: the second copy says so and stands down, rather than
OCR'ing the same chat and drawing a second overlay.

## Publishing a version

Pushing to `main` publishes a release, on its own:

1. the whole test suite runs on a Windows runner (`QT_QPA_PLATFORM=offscreen`,
   which every suite was verified to pass under);
2. the next version number is worked out from the newest `vX.Y.Z` tag;
3. `src/version.py` is stamped, so the built copy knows what it is;
4. `build.py` produces the executable and the release is published with it
   attached, notes included.

The version moves by a patch unless a commit message in the range says otherwise:
write `[minor]` or `[major]` anywhere in one. `[skip release]` in the head commit
skips the run entirely, and changes confined to `site/**`, `*.md` or `.github/**`
never trigger it — documentation is not a new binary.

The notes are the commit subjects since the previous tag, with the noise dropped
(merges, `wip`, `typo`, formatting), followed by a fixed installation section.
Edit them afterwards on the release page if you want to say more: **the site reads
the releases live**, so an edit shows up without redeploying anything.

Try the version arithmetic and the notes before pushing:

```bash
.venv\Scripts\python tools\release_meta.py            # prints, changes nothing
.venv\Scripts\python tools\release_meta.py --bump minor
```

The workflow needs no secret — `GITHUB_TOKEN` is provided to it — but the
repository must be **public** for the download page to list versions and for
anyone to download without an account.

## Sending it to someone

```bash
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python build.py            # -> dist\Flashwatch.exe   (~99 MB)
.venv\Scripts\python build.py --dir       # -> dist\Flashwatch\      (a folder)
.venv\Scripts\python build.py --out DIR   # -> DIR\Flashwatch.exe
.venv\Scripts\python build.py --console   # keeps a terminal, to see start-up errors
```

Windows will not overwrite a running program, so close Flashwatch before rebuilding
(the script says so rather than failing a minute in) — or use `--out` to build a
copy somewhere else.

`dist\Flashwatch.exe` is the whole program: **no Python, no install, nothing else to
send**. The recipient double-clicks it and it appears in the system tray. Zipping it
saves nothing (0.5%, it is already compressed) and is only worth doing for a channel
that refuses `.exe` attachments.

What they should expect:

- **Windows will warn.** An unsigned executable trips SmartScreen ("Windows
  protected your PC") — *More info* → *Run anyway*. Some antivirus products flag
  PyInstaller bundles on sight; that is the packer, not the program. Signing it
  would need a code-signing certificate.
- **First launch needs internet**, once, to fetch champion data and ~350 icons
  (9 MB). After that it runs offline.
- **It creates an `assets` folder next to itself** — settings, the icon cache and
  `flashwatch.log`. Put the .exe in its own folder rather than straight on the
  Desktop. If that location is read-only (Program Files, a network share), it
  falls back to `%LOCALAPPDATA%\Flashwatch` instead of failing to save.
- **A few seconds to start.** A one-file build unpacks itself into a temporary
  directory on every launch; measured at 2.7 s to the first log line here. The
  `--dir` build starts instantly but has to be zipped and extracted, and the .exe
  inside it will not run on its own.

Both builds were verified from a clean folder on a machine with no Python: data
downloaded, OCR engine loaded, chat area found in a live game.

### Why it is 99 MB, and why not less

A `build.py` run prints `left out N collected files`: PyInstaller's hooks collect
whole dependency trees, and most of what they gather here is never opened. The
generated spec filters the bundle itself — excluding a *module* does not remove the
C++ libraries behind it. Measured in a folder build, biggest first:

| Left out | Raw | Why it is not needed |
| --- | --- | --- |
| `opencv_videoio_ffmpeg*.dll` | 29 MB | nothing decodes video; capture is screenshots |
| `opengl32sw.dll` | 20 MB | Mesa software OpenGL, for Qt Quick — this is a raster QWidget app |
| `Qt6Quick`, `Qt6Qml`, `Qt6Pdf`, `Qt6Network`, `Qt6Svg`… | 21 MB | libraries behind the PySide6 modules already excluded |
| `PIL\_avif`, `_webp`, `_jpeg2k` | 10 MB | codecs for formats no icon here uses |
| Qt translations, `qml/`, unused plugins | ~7 MB | the app ships its own strings |

That is 316 MB → 237 MB unpacked, 134 MB → **99 MB** as one file.

The rest is genuinely used, and its floor is set by three libraries:

| Kept | Raw | Packed |
| --- | --- | --- |
| `cv2.pyd` (OpenCV) | 82 MB | 29 MB |
| onnxruntime | 33 MB | ~13 MB |
| OCR models | 15 MB | ~14 MB |
| numpy + OpenBLAS | 25 MB | ~10 MB |
| Qt6Core/Gui/Widgets + bindings | 35 MB | ~14 MB |

OpenCV is the obvious target and it cannot go: `rapidocr_onnxruntime` imports it
too, so removing it means replacing the OCR engine, not just this app's own image
handling. `opencv-python-headless` was measured and rejected — its `cv2.pyd` is
81.9 MB against 82.3, because the GUI parts of OpenCV were never the heavy bit.
UPX was left off deliberately: it barely helps a bundle that is already
zlib-compressed, and it makes antivirus false positives markedly more likely.

Going meaningfully below ~90 MB would mean a different OCR stack.

## Play in borderless, not exclusive fullscreen

Windows does not allow any overlay to draw over an exclusive-fullscreen game.
Set League to **Borderless** in video settings. Everything else works either way.

## Language

French and English, picked in **Réglages → Langue / Language**. One choice drives
three things: the wordings looked for in chat, the champion and spell names
downloaded from Data Dragon, and the interface itself.

Set it to whatever **your League client** is in — that is the language the chat is
printed in. Switching applies straight away: the settings window and tray menu are
rebuilt, and the Riot data for the new locale is fetched in the background (any
running timers are cleared, since their champion names came from the old one).

| Form | French | English |
| --- | --- | --- |
| cast — what a game prints | `Ahri a utilisé Saut éclair` | `Ahri used Flash`, `Ahri has used Flash` |
| stated cooldown — typed, to test | `Attendez Ahri Saut éclair - 245 sec.` | `Wait Ahri Flash - 245 sec.`, `Wait for Ahri's Flash - 245 seconds` |

Nothing is hardcoded: names come from Data Dragon, and the English spell names are
indexed whichever locale is loaded, so an English client still reads correctly if
the app is left on French data. Another language can be added by extending
`SYSTEM_VERBS` and `WAIT_RE` in `message_parser.py` and the table in `i18n.py`.

## How the chat area is found

Chat position depends on resolution, HUD scale and window mode, so nothing is
hardcoded. The app keys on chat's *content* rather than its shape:

1. **Explore.** Read the generous lower-left band of the window.
2. **Confirm.** A row is a chat line if it opens with a `(mm:ss)` clock, carries
   an author prefix (`Nom (Champion): …`), or matches the cooldown wording. Those
   rows define the chat region, which is then saved.
3. **Narrow.** Once confirmed, only that small region is read.

Several signals are needed because chat timestamps are a client option, so the
tracker pings do not necessarily carry one — a clock alone is too narrow an
anchor. None of these forms can be produced by terrain, minions or health bars.

> An earlier version instead recognised chat by its *shape* — clustering
> left-aligned rows of glyph edges. It passed synthetic tests and failed
> completely on real footage, locking onto scenery in the middle of the screen
> and reporting a different answer every few seconds. The test backgrounds were
> too clean; they now carry heavy high-frequency clutter.

## If nothing is detected

**Type `Attendez Darius Saut éclair - 245 sec.` in chat.** A timer must appear at
once. That single line separates the two halves of the pipeline: if it works, the
capture and the OCR are fine and you are simply waiting for an enemy to use a
summoner spell; if it does not, the chat area is wrong or the language does not
match your client.

Then open **Settings → Debug**. It shows every line the OCR read, plus "near
misses": lines that named a champion but did not parse. If the system wording in
your client differs from what the parser expects, it will appear there, and
`SYSTEM_VERBS` in `src/message_parser.py` can be adjusted to match.

If the chat area itself was not found, use **Settings → Statut → Définir la zone
manuellement** and drag a rectangle around the chat. A manual region is saved and
always takes priority over automatic detection.

### Mode test : placer la zone à la main, en voyant ce qu'elle lit

Drawing a rectangle blind tells you nothing about whether it works. **Settings →
Statut → Mode test : placer la zone OCR** (also in the tray menu) puts a frame on
screen around the area actually being captured, and keeps it there while you
adjust it:

* drag the **edges** to move or resize it, or nudge with the **arrow keys**
  (1 px, `Maj` = 10 px, `Ctrl` = resize);
* the capture worker follows the frame as it moves, so the readout under it
  updates within a fraction of a second: how many rows were read, how many were
  recognised as chat lines, and the last chat line in full;
* green ticks down the left margin mark where each recognised row sits, so a
  frame that is too short or aimed at the scoreboard is obvious;
* the border turns **green** as soon as chat lines are being read;
* **Valider** saves the rectangle as the manual region, **Annuler** / `Échap`
  restores whatever was in use before — nothing is persisted until you validate.

The middle of the frame is genuinely empty: the window is a ring, cut out with a
mask, so the frame can never paint into the screenshot it is aiming, and clicks
in the middle still reach the game. Test mode also reads with League closed, so
the zone can be set up on a replay or a screenshot.

Unlike the timer overlay, this frame *does* take focus — the arrow keys have to
reach it — so clicking it during a game hands focus to it for as long as it is
open. It is a setup mode: validate, close it, and the overlay goes back to never
touching focus.

### Three areas, same frame

The chat is found automatically. The other two areas cannot be: a match timer is
five glyphs with no signature to search for, and the scoreboard only exists while
`Tab` is held. So each has its own button (and tray entry), and each opens the same
frame — several can be open at once:

| Button | What it is for |
| --- | --- |
| **Mode test : zone du chat** | the chat, as above |
| **Mode test : zone du temps de partie** | the match timer at the top of the screen |
| **Mode test : zone du scoreboard** | the `Tab` panel |

Each frame judges itself on what its area is *for*, not on row counts: the clock
frame shows the time it parsed (`horloge lue : 12:34`) or says it cannot read one —
five glyphs are one row whether they read `12:34` or `l2;3A`. The scoreboard frame
shows the lines it read. Each area is saved separately and reopens where you left
it, and the clock frame can be much smaller than a chat line so it does not have to
swallow the minimap.

**The clock, once validated, is used.** It is the game time itself, so it replaces
the timestamps prefixing chat lines — which the player can switch off, and which
the OCR can misread. That is what makes reading a line late cost nothing: the app
knows how old it was. Two consecutive readings must agree before the clock moves,
since the reference only ever advances and one misread would stick.

**The scoreboard is read and shown, but not yet interpreted.** Placing it now is
what the planned reader (enemy items → real ability haste, instead of assuming
runes) will use. Its area is only read while its frame is open, so a saved
scoreboard costs nothing.

For a deeper look, run the diagnostic during a game:

```bash
.venv\Scripts\python tools\diagnose.py
```

It saves real screenshots plus every line it can read from the lower-left of the
screen into `assets/diagnostics/<timestamp>/`, which answers the questions a log
cannot: whether a ping writes a chat line at all, its exact wording, and where
it appears.

## Enemies only — an option, off by default

The wording a real game produces (`Ahri a utilisé Saut éclair`) is printed for
enemies only, so it is taken at face value and never filtered.

The stated-cooldown form is the ambiguous one: `Attendez Ahri Saut éclair - 245
sec.` reads identically whether Ahri is the enemy mid or somebody's own cooldown.
Its text says nothing about teams, but the screen does — the game draws **enemy
champion names in red** — so **Réglages → Suivi → Uniquement les ennemis** can make
that form's pixels decide.

It ships **off**, and the reason is the same fact: that form is in practice a line
you type yourself to test the OCR, and your own typing is not drawn red — left on,
the option would reject exactly the line used for testing. Turn it on only if you
see timers appear for spells that were not an enemy's.

The test looks at the row that was read, isolates its text strokes, and asks
whether one word is markedly redder than the rest of that line's text. It has
three outcomes rather than two:

| Verdict | Action |
| --- | --- |
| a red, word-shaped name | timer starts |
| no red name | ignored, and listed in **Debug** so it stays visible |
| the row's text is red across the board (chat with no panel over the red base, a particle burst) | nothing concluded; the line is read again on a later frame, once the game has moved behind it |

The third case matters: chat lines stay on screen for seconds, so declaring such a
row "ally" would silently lose real pings, while calling it "enemy" would trust a
red background. Waiting costs nothing.

## Accuracy

In a game, the cooldown comes from the game's table rather than from a stated
number, so the assumptions matter. **Cosmic Insight** (18% summoner haste) is
assumed by default — Flash is 246 s rather than 300 s — and Ionian Boots can be
assumed too, both in **Réglages**. The rune is near-universal, which is why it is
the default; a wrong assumption there is the difference between 246 s and 300 s.

| Source | Accuracy |
| --- | --- |
| `a utilisé` / `used`, summoner spell | Base cooldown from the table, adjusted by the haste assumptions above. Exact when they match reality. |
| `a utilisé` / `used`, ultimate | Approximate, shown with a `~` prefix. |
| `Attendez … - N sec.` (typed, to test) | **Exact**, summoner spells *and* ultimates: the number is stated, nothing is guessed. |

Ultimate cooldowns depend on ability rank and haste, neither visible on screen, so
rank is inferred from the game clock and per-champion haste can be set in
`assets/settings.json`. The planned scoreboard reader will fill that in from enemy
items.

## Overlay

Two layouts, switchable in **Settings → Réglages → Disposition**.

**Barre en haut** (default) — a discreet strip at the top centre of the screen.
Each spell on cooldown is a champion portrait with its spell badged on the corner,
riding the track **left to right** as the cooldown runs down: it enters at the
left the moment a spell is used and arrives at the right as it comes back up. So
"who is nearly back" is readable without reading any numbers.

The bar stays **off screen until you are in a game**: nothing is drawn on the
desktop, in the client or in champion select. It appears when League's in-game
window does, and goes away when the game ends. Untick **Masquer la barre tant
qu'on n'est pas en partie** to have it up all the time; it is also always shown
while unlocked, so it can still be positioned with League closed.

When a spell comes back up its marker reads **READY** at the right-hand end of the
track for a few seconds, then its entry disappears — long enough to be read as
confirmation, short enough that the bar keeps showing only what is actually down.
The delay is **Garder READY affiché** in the settings (5 s by default; 0 removes
the entry the moment it is ready, and the audio cue still fires).

With nothing on cooldown the bar fades to just its track — faint, but enough to
show the app is alive and where it sits. Untick **Afficher la barre vide** to make
it fully invisible at rest instead.

To check it without waiting for a game, use **Afficher un aperçu (test)** (tray
menu or settings): it puts three fake 20-second timers on the bar so position,
theme and scale can be judged immediately. The short times make a preview
impossible to mistake for real data.

**Liste verticale** — the original panel, one row per spell.

Two spells used in the same second land on the same point of the track, so the
markers are placed as a group: each is nudged sideways just enough to clear its
neighbour, and the run is pushed back inside the bar's edges rather than piling up
against them. If more cooldowns are running than the bar has room for, they are
spread evenly over its full width — crowded, but never one portrait hidden behind
another. The time text remains the precise readout.

Use **Recentrer la barre en haut de l'écran** after changing resolution, and
uncheck **Verrouillé** to drag or resize it.

## Layout

```
src/
  main.py            entry point, threading and wiring
  overlay.py         transparent click-through overlay
  ui.py              control window, settings, debug view, region picker
  zone_overlay.py    test-mode frame: place the OCR zone by hand, live
  ocr.py             capture loop, OCR, work-avoidance layers
  chat_detector.py   locates the chat without hardcoded coordinates
  message_parser.py  OCR text -> confirmed spell events
  timer_manager.py   active cooldowns, dedupe, age correction
  game_detector.py   League process/window detection
  riot_assets.py     Data Dragon data and icon cache
  cooldowns.py       cooldown table
  i18n.py            every user-facing string, French and English
  settings.py        persisted configuration
  audio.py           notification tones
build.py             packages everything into one .exe to send
site/
  index.html         download page: install guide, docs, live overlay mock
tools/
  diagnose.py        in-game capture + OCR dump for troubleshooting
tests/               runnable checks, see below
assets/cache/        downloaded icons and data (created on first run)
```

## Tests

Each file is a standalone script that exits non-zero on failure:

```bash
.venv\Scripts\python tests\test_message_parser.py     # parsing and rejection
.venv\Scripts\python tests\test_wait_messages.py      # the real ping format
.venv\Scripts\python tests\test_faded_chat.py         # chat box CLOSED, faded text
.venv\Scripts\python tests\test_all_champions.py      # all 173 champions x 9 spells
.venv\Scripts\python tests\test_timer_manager.py      # dedupe, stale history, ults
.venv\Scripts\python tests\test_capture_pipeline.py   # detection at 1080p..4K
.venv\Scripts\python tests\test_ocr_performance.py    # work-avoidance layers
.venv\Scripts\python tests\test_app_shell.py          # tray menu, quit routes, overlay, test mode
.venv\Scripts\python tests\test_zone_frame.py         # the test-mode frame and its empty middle
.venv\Scripts\python tests\test_enemy_colour.py       # red name = enemy, over every backdrop
.venv\Scripts\python tests\test_bar_layout.py         # markers never overlap on the bar
.venv\Scripts\python tests\test_english_client.py     # the same messages, EN client
.venv\Scripts\python tests\test_language.py           # the catalogue and the switch
.venv\Scripts\python tests\test_timer_stability.py    # nothing may move a set timer
.venv\Scripts\python tests\test_extra_zones.py        # clock and scoreboard areas
```

`test_capture_pipeline.py` and `test_ocr_performance.py` render synthetic
game-like frames, so they exercise the real detection and OCR code without
needing League running.

## Performance

Measured at 1080p on the development machine:

| | Cost |
| --- | --- |
| Idle frame (chat unchanged) | 0.10 ms — about 0.05% of one core at 5 Hz |
| Re-reading a region whose pixels are identical | 1.1 ms |
| Full read of the confirmed region | ~173 ms |
| Region showing only scenery (chat box closed) | ~162 ms |
| Explore pass (locating chat) | 0.6–1.3 s, throttled to once per 0.7 s |
| Clock zone, when configured | 20 ms every 0.9 s — about 2% of one core |

**Worst-case latency to read a new message: ~1.4 s** (the 1.2 s forced re-read
plus one full read). Worst-case CPU is one 162 ms read every 1.2 s — 13.5% of a
single core, roughly 1.7% of an 8-core machine — and only while the chat area
shows moving scenery. With chat static it drops to the 1.1 ms path.

Work is avoided in three places: a frame gate comparing glyph masks (so the game
world moving behind chat is not mistaken for new text), custom OpenCV row
segmentation instead of the OCR detection network (480 ms → 168 ms), and a
per-row recognition cache.

A **region confirmed in an earlier session is reused** on the next launch, which
skips the slow explore phase entirely. It is discarded if the window size changed.

> The row cache is keyed on an **exact** pixel hash. It was originally a tolerant
> image fingerprint, which measurement showed cannot work: two pings differing
> only in their seconds value ("245" vs "240") are indistinguishable at any
> downscale, while the *same* line over a darker background differs more than they
> do. A false hit served another line's cached text, so new pings were never read
> — the cause of "I pinged twice and it didn't register". An exact key can only
> miss, costing time rather than correctness.

## Known constraints

- **Python 3.11, not 3.13.** `rapidocr-onnxruntime` has no wheels for Python
  3.14, which is what is installed here alongside 3.11. 3.13 also works if you
  have it.
- **Chat detection is still unverified against a real game.** The timestamp-driven
  approach is validated on synthetic frames at 1080p/1440p/4K across HUD scales,
  with heavy background clutter, but only real footage proves it. While
  unconfirmed the app reads the whole lower-left band, so a detection miss
  degrades to "slower" rather than "reads the wrong pixels".
- **The exact system wording is assumed.** Data Dragon supplies champion and
  spell names but not client UI strings, so the verb phrase (`a utilisé`) comes
  from the observed message format. Confirm it in the Debug tab on first use.
