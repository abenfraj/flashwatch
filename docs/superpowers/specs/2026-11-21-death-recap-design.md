# Death recap reader -- design

## Intent

When the player dies, League shows a recap panel at the top left of the screen:
one row per enemy who dealt damage -- portrait, damage, damage-type bar -- and, on
the right of each row, the icons of what did the damage. A summoner spell that
appears there was used, whether or not anybody pinged it. Flashwatch reads the
panel and starts that spell's timer when it is not already running.

## Goals

- Read the panel whenever it appears, in a game and on a stream alike.
- Start the timer of every enemy summoner spell the panel shows, unless a timer
  for that champion and spell is already running.
- Never be the reason a timer says "down" while the spell is back up.

## Non-goals

- Flash, Exhaust, Heal, Barrier, Cleanse, Ghost, Teleport: they deal no damage
  and never appear in the panel. In practice the panel yields Ignite and Smite.
- Champion abilities and ultimates shown in the panel.

## Anti-goals

- A timer started from a champion ability icon that resembles a summoner icon.
- A recap reading replacing a timer that a chat ping already set.

## Decisions (Ayoub)

- **Trigger: the panel itself.** Reading starts when the panel is on screen and
  stops when it is gone -- not from the game feed's "dead" flag.
- **Timing: the start of the fight.** The panel's header shows how long the
  fight lasted ("24.7s"). The cast is placed at the moment the panel appeared
  minus that duration, so a timer can end early but never late.

## Approaches considered

1. **Image recognition (chosen).** Portraits matched with the scoreboard's icon
   matcher, spell icons matched against Data Dragon's summoner icons. The only
   way that works: the panel prints no names.
2. OCR only -- rejected, there is no text naming champions or spells.
3. Chat kill messages / game feed -- rejected, neither names the spells used.

## Design

- **Where:** a generous area at the top left of the game window, as a share of
  its size (no fixed position: resolution and HUD scale vary).
- **Detecting the panel:** champion portraits found in that area by the icon
  matcher, restricted to the five enemies when the game feed names them, all
  champions otherwise. At least one confident portrait row plus the panel's
  layout (portraits stacked in a column) means the panel is up.
- **Reading a row:** to the right of each portrait, search for that enemy's own
  two summoner icons (from the feed) -- or all summoner icons, with a stricter
  threshold, when there is no feed.
- **Fight duration:** OCR of the header number followed by "s". Unreadable:
  25 s, the cautious side.
- **Confirmation:** a spell is adopted only when two successive readings agree,
  as the scoreboard reader does.
- **Timer:** cast time = panel first seen - fight duration; marked uncertain
  ("?"); never replaces a running timer; a later confirmed chat line re-anchors
  it through the existing uncertain-to-certain path.
- **Setting:** "Read the death recap", on by default.
- **Trace:** every reading written to the trace log.
- **Fixture:** the 13:45 death from the ratirl recording (Thresh's Ignite, to be
  confirmed by the matcher) as the reference frame for tests.

## Left to the builder

- Exact search area shares, icon scales and thresholds, measured on the fixture.
- Cadence while the panel is up (it stays a few seconds; one look a second is
  plenty), and the cheap check that says it is not up.
