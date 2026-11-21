# Death Recap Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the death recap panel is on screen, read which enemy summoner spells it shows and start their timers (uncertain, placed at the start of the fight) unless already running.

**Architecture:** A pure module `src/death_recap.py` finds the panel's enemy rows by matching portraits (the scoreboard's `IconMatcher`), keeps only red-framed rows (the gold row is the player), looks for each enemy's summoner icons to the right of its portrait, and reads the fight duration by OCR. `CaptureWorker` runs it about once a second while in a game, adopts a spell only when two readings agree, and publishes it; `main` hands it to `TimerManager.note_recap`.

**Tech Stack:** Python 3, OpenCV, numpy, RapidOCR (existing `OcrEngine`), PySide6 for the setting.

**Spec:** `docs/superpowers/specs/2026-11-21-death-recap-design.md`

## Global Constraints

- Trigger is the panel itself, not the game feed's "dead" flag (Ayoub).
- Cast time = moment the panel was first seen − fight duration; unreadable duration = 25 s (Ayoub).
- Timer is uncertain ("?"), never replaces a running timer, and a confirmed chat line re-anchors it.
- Only red-framed rows are enemies; the gold-framed row is the player and is ignored.
- No fixed screen position: the search area is a share of the game window.
- Setting `read_death_recap`, default `True`.
- Every reading goes to the `trace` logger.

## Review Focus

- The gold row (the player's own spells): must never yield a timer — fixture test.
- An ally's portrait in a red row cannot happen, but the open field without a roster can match a wrong champion: require the red frame *and*, with a roster, membership of the five enemies.
- A champion ability icon that looks like Ignite (fire art): with a roster only that enemy's two spells are candidates; without one, a stricter score — synthetic negative with a fire ability icon.
- The panel staying up for the whole death (several seconds): one adoption per spell per panel appearance, not one per frame — worker test.
- The panel reappearing on the next death: a new appearance, new cast time — worker test.

---

### Task 1: `death_recap.py` — read a frame

**Files:**
- Create: `src/death_recap.py`
- Create: `tests/fixtures/death-recap-1080p.png` (top-left 400×540 crop of the 13:45 ratirl death; rows Taliyah, Zed, a non-champion, then the gold Twitch row)
- Test: `tests/test_death_recap.py`

**Interfaces:**
- Produces:
  - `search_area(window_rect) -> tuple[int, int, int, int]` — `(x, y, w, h)` on screen: left 22% × top 50% of the window.
  - `@dataclass RecapRow: champion_id: str; box: tuple[int, int, int, int]; enemy: bool; spells: frozenset[str]`
  - `@dataclass RecapReading: rows: list[RecapRow]; fight_seconds: float | None` with property `enemy_spells -> frozenset[tuple[str, str]]` (champion_id, spell_key) over enemy rows only.
  - `class SpellIconMatcher(assets)` with `build() -> int` and `score(crop, spell_key) -> float` (circular-inset descriptor against `assets.icon_for_spell`).
  - `read(area_bgr, champions: IconMatcher, spells: SpellIconMatcher, enemies: dict[str, frozenset[str]] | None, rows_text: list[tuple[str, tuple]] ) -> RecapReading | None` — `None` when no panel (fewer than one red-framed portrait in a column).
  - `parse_fight_seconds(text: str) -> float | None` — "24.7s" → 24.7; accepts "24,7s", "24.7 s"; rejects values outside 0.5–120.

- [ ] **Step 1: Write the failing tests** in `tests/test_death_recap.py`:
  - `parse_fight_seconds("24.7s") == 24.7`, `("24,7 s") == 24.7`, `("0.0s") is None`, `("499") is None`.
  - Fixture with roster `{Taliyah: {Flash, Ignite}, Zed: {Flash, Ignite}, ...}`: reading is not None; enemy rows' champion ids ⊇ {"Taliyah", "Zed"}; no row has champion "Twitch" marked enemy; `enemy_spells == frozenset()`.
  - Same fixture without a roster: Twitch row, if found, has `enemy is False`; `enemy_spells == frozenset()`.
  - Synthetic positive: fixture with Data Dragon `SummonerDot` pasted as a 22 px circle at the right of the Zed row → `("Zed", "Ignite") in enemy_spells`.
  - Synthetic negative: Zed's own ultimate icon pasted in the same spot, without a roster → no spell for Zed.
  - A frame of plain game world (from the recording, no panel) → `read(...) is None`.
- [ ] **Step 2: Run** `.venv\Scripts\python.exe tests\test_death_recap.py` — expect failures (module missing).
- [ ] **Step 3: Implement** `src/death_recap.py`: portraits by sliding the champion matcher down the left 30% of the area at scales 0.045–0.065 × window height; red frame = mean of a 2 px ring around the portrait with R > G+40 and R > B+40; gold = R,G > B+40; spells searched in the row band right of the damage bar at 0.6–0.8 × portrait size; fight seconds from OCR rows above the first portrait.
- [ ] **Step 4: Run** the test — all PASS.
- [ ] **Step 5: Commit** `Read the death recap panel's enemy rows and spells`.

### Task 2: Worker — read while up, adopt on agreement

**Files:**
- Modify: `src/ocr.py` (`CaptureWorker`, `PipelineStatus`)
- Test: `tests/test_death_recap.py` (worker section, synthetic frames through `_grab`/detector seams as in `tests/test_capture_guards.py`)

**Interfaces:**
- Consumes: Task 1's `search_area`, `read`, `SpellIconMatcher`.
- Produces: `PipelineStatus.recap_events: list[tuple[str, str, float]]` — `(champion_id, spell_key, cast_clock)` where `cast_clock = clock.now()` at first sight of this panel − fight seconds (25 if unknown); each `(champion, spell)` published once per panel appearance. `CaptureWorker.set_recap_enabled(bool)`; `CaptureWorker.set_recap_roster(dict | None)`.

- [ ] **Step 1: Tests:** two identical readings → one event; one reading then none → no event; panel gone for > 3 s then back → a second appearance with a new cast clock; disabled → nothing read.
- [ ] **Step 2: Run** — fail.
- [ ] **Step 3: Implement**: `RECAP_INTERVAL = 1.0` s, in game and not paused; appearance ends after `RECAP_GONE = 3.0` s without a reading; every reading traced (`trace.info("recap %s", ...)`).
- [ ] **Step 4: Run** — pass; `tests/test_capture_pipeline.py`, `tests/test_ocr_performance.py` still pass.
- [ ] **Step 5: Commit** `Read the death recap while it is on screen`.

### Task 3: Timers, wiring, setting

**Files:**
- Modify: `src/timer_manager.py`, `src/main.py`, `src/settings.py`, `src/ui.py`, `src/i18n.py`
- Test: `tests/test_death_recap.py` (timer section)

**Interfaces:**
- Consumes: Task 2's `status.recap_events`.
- Produces: `TimerManager.note_recap(champion_id: str, spell_key: str, cast_clock: float) -> ActiveTimer | None`.

- [ ] **Step 1: Tests:** no timer → uncertain timer whose remaining = duration − (now − cast_clock); a running timer for that spell → `None`, untouched; a later confirmed chat line re-anchors it (uncertain cleared); a spell not in the roster for that enemy → `None`.
- [ ] **Step 2: Run** — fail.
- [ ] **Step 3: Implement** `note_recap` reusing `_duration_for`/`ActiveTimer`; `main._drain_results` forwards `recap_events` (deduped by the worker) and the live roster to the worker; setting `read_death_recap` (default True) with a switch on the Troubleshooting/Detection page, labels "Lire l'écran de mort" / "Read the death recap".
- [ ] **Step 4: Run** — pass; full suite passes.
- [ ] **Step 5: Commit** `Start timers from the death recap`.

### Task 4: Live check

- [ ] Restart `tools/watch.py` on the stream; on ratirl's next deaths, the trace shows a recap reading per death, with the right enemy rows and no timer from the gold row.
