# FLASHWATCH — ART DIRECTION KIT (single file)

## §0 — HOW TO USE THIS FILE

You are the art director for the Windows desktop app described below. This file is
the entire brief: the product, the surfaces, the technical limits, five candidate
directions, and twelve numbered tasks.

**Do not execute any task yet.** Read the whole file, then reply exactly as §10 says
and wait. The human will then ask for tasks by number, in one conversation, in
order. Every task depends on the answers to the ones before it — especially TASK 1,
which fixes the palette everything else must use.

Task index:

| # | What it produces |
| --- | --- |
| 1 | The token table (exact values) + a mood board — **gates everything else** |
| 2 | A cooldown in its six states, one sheet — the most useful image of all |
| 3 | The chrono track, over a simulated game |
| 4 | The fixed cards, over a simulated game |
| 5 | The compact rows, over a simulated game |
| 6 | The overlay at rest, and while being positioned |
| 7 | The overlay over a **bright** background — the test that decided the palette |
| 8 | The desktop window's component sheet |
| 9 | The desktop window: home page, display page, dense pages, update banner |
| 10 | The setup guide: its frame, its six figures, its step indicator |
| 11 | The app mark: candidates, the 16 px test, then its geometry as numbers |
| 12 | Restyle the HTML mockup — for this one the human attaches a second file, |
|    | `design/maquette/index.html`. Ask for it if it is not attached. |
| 13 | The six onboarding screens, set up inside League's Practice Tool |

---

## §1 — THE PRODUCT

Flashwatch watches the player's screen during a League of Legends match. When the
game prints in the chat that an enemy has used a summoner spell, the app reads that
line with OCR and starts a countdown, then shows those countdowns in a small
always-on-top overlay drawn over the game. It never injects into the game, never
reads its memory, never sends input: it only reads pixels already on screen. It is
not affiliated with Riot Games in any way.

Its users are League players, mid-match, under stress, glancing for a fraction of a
second. **The single most important pixel in the product is a countdown like "4:23"
read at a glance over a busy, bright, moving game.**

The interface today is light: a cool near-white ground, a deep blue accent, and an
overlay that is a near-opaque light panel with dark numerals — deliberately, because
that is the only combination measured to stay legible over both a dark cave and a
bright victory screen (over 10:1 on both, where white-on-translucent-dark scored
3.56:1 on the bright one). It is legible and it has no character. Keeping it light
is not negotiable; giving it a point of view is what you are here for.

---

## §2 — THE SURFACES

**1. THE OVERLAY** — drawn over the game, translucent, always on top,
click-through. Three interchangeable displays of the same data; the user picks one.

- **a) CHRONO TRACK** — a wide shallow strip, ~560×78 px, at the top centre of the
  screen. A thin rail runs across it with a tick at each end and its rightmost sixth
  tinted with the "ready" colour. Each cooldown is a circular champion portrait with
  a small circular spell badge on its lower right, hanging *below* the rail and
  joined to it by a short vertical stem in its own state colour, positioned along the
  rail according to how far through the cooldown it is — entering at the left when
  the spell is cast, arriving at the right as it comes back up. The countdown sits
  directly under each portrait.
- **b) FIXED CARDS** — a compact strip, ~460×104 px. One card per cooldown in a slot
  that never moves: a tiny uppercase role label (TOP, JUNGLE, MID, ADC, SUPPORT), a
  circular portrait with a **progress ring** closing around it clockwise from the
  top, a spell badge on its lower right, the countdown below.
- **c) COMPACT ROWS** — a tall narrow panel, ~300×330 px. One row per cooldown:
  portrait, spell badge, champion name, spell name under it, countdown right-aligned,
  and a thin horizontal progress gauge along the bottom of the row. Rows are grouped
  under small uppercase role headings. This is the most opaque of the three — it is a
  panel, not a strip — but the game still shows through faintly.

**2. THE CONTROL WINDOW** — a normal desktop window, ~620×680 px. A header with the
app mark, its name, a one-line tagline and a small state pill; a vertical navigation
column on the left with four entries (Home, Display, Settings, Troubleshooting); a
scrolling content column of cards; a footer with two buttons.

**3. THE SETUP GUIDE** — a ~650×740 px window shown once on first run. Six steps,
each with a large schematic illustration above a title, a paragraph, and a note box.
A footer with a six-dot step indicator and back/next buttons.

**4. THE MARK** — one small icon that must work at 16 px in the Windows notification
area and at 34 px in a window header. Today: a dark disc with a cyan rim and two
white clock hands. Deliberately abstract.

**THREE STATES CARRY MEANING** and must stay distinguishable at a glance:
counting down (neutral, the default) · nearly back up, under 30 seconds (a warning
colour) · back up / READY (a positive colour). Two extra marks: a small "?" chip on a
spell badge when the app only *inferred* which spell was used, and a "~" before a
countdown that is an estimate.

---

## §3 — WHAT CAN AND CANNOT BE BUILT

Everything is drawn with Qt/PySide6 — QPainter for the overlay and the guide's
figures, Qt Style Sheets for the desktop widgets. **A direction that needs anything
in the second list cannot ship**, so propose the replacement instead.

**Available, use freely:** flat fills · linear, radial and conical gradients ·
per-pixel alpha · rounded rectangles, circles, arcs, rings · clipping to arbitrary
paths · hairlines and dash patterns · layered translucency · **hand-painted** shadows
and glows (a second offset translucent pass) · geometric textures such as grids,
guilloché, hatching, halftone (baked once into a bitmap, then reused) ·
letter-spacing on uppercase labels · per-state widget styling (hover, checked,
focus, disabled) · bundled TTF fonts.

**Not available — never propose these:**

| Impossible | Use instead |
| --- | --- |
| Background blur / frosted glass over the game | a more opaque or gradient backing |
| `box-shadow`, `text-shadow` on a widget | a painted offset shadow |
| `text-transform` | text already in the right case |
| `transition`, `animation`, `transform` | nothing, or a Qt animation off the overlay |
| Per-frame blur or image filters | a glow baked once at start-up and cached |
| Photography, 3D renders, mesh gradients, generated imagery | geometry |

**Overlay-specific limits, which is where directions usually break:**

- It repaints ~10 times a second over a running game, inside a 3% CPU and 200 MB
  budget. Nothing expensive per frame.
- On a translucent window, **sub-pixel text antialiasing is off**. Thin light text
  always looks weaker than in a mockup: at small sizes prefer medium weights, and
  the painted shadow is not a luxury.
- The user scales it from **0.6× to 2.0×**. A direction that only holds because of a
  1 px hairline dies at 0.6 and doubles at 2.0. Express everything proportionally.
- It never takes focus and passes clicks through, so **there is no hover state**. A
  design that needs hover to be understood cannot exist here.
- It must stay legible from the black of a cave to the white of a victory screen.

**Desktop-window limits:** a checkbox does not wrap its label, so switch labels stay
short and explanations go in a dim line underneath · layout comes from Qt layouts,
not from the stylesheet, so a mockup must decompose into stacked rows and columns.

**Typography:** any typeface you recommend must be free to embed — **SIL OFL or
Apache-2.0 only** — and named precisely, with its licence stated. Numerals **must**
be tabular: a countdown that changes width every second is unusable.

---

## §4 — RULES FOR EVERY IMAGE YOU GENERATE

These apply to tasks 2 through 11 without being repeated. Assume them.

1. **Flat vector-style UI design.** No photography, no 3D, no isometric
   perspective, no painterly rendering *of the interface itself*.
2. **No device frames, no browser chrome, no OS title bar, no cursor, no watermark,
   no signature, no logos of any kind.**
3. **No Riot Games imagery.** No artwork, no champion art, no in-game screenshots,
   no game logos, no fantasy or medieval iconography anywhere. Champion portraits
   are plain grey circles with two initials in them. Spell badges are plain abstract
   glyphs or single letters.
4. **Use the exact palette from the token table of TASK 1.** Do not drift, do not
   "improve" it per image, do not lighten or darken it to make an image work.
5. **Where a task asks for a simulated game background**, paint an abstract blurred
   scene — cool blues and teals with some warm highlights, or the bright variant when
   asked. No recognisable characters, creatures, text or logos. It exists only to
   prove the overlay stays legible on it.
6. **Text content does not matter and will be misspelled** — that is expected and
   irrelevant, the real strings come from the app's own catalogue. Keep labels short
   so the layout stays readable. What matters is palette, form, texture, hierarchy.
7. **Render large enough** that ring thickness, badge overlap, hairlines and numeral
   treatment are all clearly readable, with generous margins so the image can be
   cropped.
8. One idea per image. If you want to show variants, put them in a labelled grid
   inside one image rather than hedging within a single mockup.

---

## §5 — THE FIVE DIRECTIONS

Pick **one** when the human tells you which. Do not blend them, do not hedge, and do
not soften whichever one is chosen into a generic dark dashboard — that is precisely
what the app looks like today.

**A — FLIGHT INSTRUMENT.** A glass cockpit. Deep almost-blue black, engraved
half-pixel rules, bezels that catch light like brushed metal, ONE signalling amber
and one standby cyan and nothing else. Condensed numerals aligned in columns,
graduations along the rails, labels as small silkscreened capitals with wide
tracking. *Vocabulary:* glass cockpit, altimeter tape, engraved bezel, silkscreened
label, warning amber, graticule. *Risk:* timidity — this is the family the current
interface gestures at, so it needs real contrast and genuinely engraved separators,
not polished greys.

**B — BROADCAST GALLERY.** The graphics package of a live esports broadcast. Heavy,
wide, slightly italic numerals, pure white on dense black, flat team-colour bars laid
in as solid blocks, massive pills, diagonal cuts that imply motion. *Vocabulary:*
lower third, scoreboard bug, broadcast ticker, team colour bar, extended bold
numerals, on-air red. *Risk:* noise — on a permanently visible overlay the weight can
shout, so the at-rest state must be genuinely quiet.

**C — WATCHMAKER'S BENCH.** The program is a stopwatch, so commit to it. Warm
charcoal, brass and steel, a very discreet guilloché texture on panels, engraved
index marks around the progress rings, fine engraved or lightly serifed numerals. The
state colour arrives like a red hand on a dial: rare, therefore read. *Vocabulary:*
guilloché, brushed brass, chronograph subdial, engraved index marks, tachymeter
bezel, applied hands, sunburst finish. *Risk:* temperature — brass must stay legible
over a cool blue-green game scene. *This is the direction that justifies the progress
rings rather than decorating with them.*

**D — AMBER TERMINAL.** Monochrome. Amber on black, everything monospaced,
rectangular frames with single hairlines, no gradients at all, a barely perceptible
scanline texture. States do not change hue, they change **intensity**: standby,
normal, full-brightness alert. *Vocabulary:* amber phosphor, VT terminal, scanline,
monospaced grid, dim/bright intensity, box-drawing rules, character cell. *Risk:*
cliché — it needs real terminal vocabulary (columns, table rules, intensity levels),
not just glowing green.

**E — TECHNICAL PAPER.** Ink on tracing paper, or its negative. A halftone grid,
dimension lines and registration marks borrowed from engineering drawing,
annotations in monospace, a single correction red. Portraits are circles ringed with
a fine stroke, like parts referenced on a plan. *Vocabulary:* blueprint, drafting
grid, dimension lines, registration marks, Swiss technical, halftone, part callout.
*Risk:* ground — a pale panel vanishes over a bright game, so this direction requires
a more opaque panel, which must be stated explicitly.

---

## §6 — TASK 1 · THE TOKEN TABLE AND THE MOOD BOARD

Everything else depends on this one. Two deliverables, in this order.

**FIRST, the token table.** Exact hex values, one per role, no ranges, no "or", no
prose. These are the roles the code actually uses, so use these names verbatim:

```
field            the window's own ground
field_2          a second ground, for headers and inset areas
panel            a card or panel surface
panel_2          the second stop of a panel's vertical gradient
line             a hairline separator
line_strong      a hairline that needs to be seen
ink              primary text
ink_dim          secondary text
ink_faint        labels, captions, disabled
accent           the one colour the identity is built on
accent_wash      the accent at low alpha, as an rgba() string
counting         a countdown that is neither soon nor ready
soon             under 30 seconds
ready            back up
danger           destructive actions and errors
overlay_panel    the overlay's backing, as rgba() — it sits over a live game
overlay_rail     the chrono track's rail
overlay_row      the tint behind one row of the compact list
badge_backing    the opaque disc a spell icon sits on
```

Then, as numbers:

- the overlay's backing opacity in play and at rest (two values, 0–1)
- corner radii: overlay, card, row, pill, badge
- stroke widths: hairline, panel border, progress ring, portrait ring, row gauge
- a spacing scale of five steps in pixels
- the offset and alpha of the painted shadow under the countdown text

Then **typography**: a display face, a body face, and a face for numerals and small
uppercase labels. Real families, free to embed, licence stated for each. For each
give the weights used and the pixel sizes for: window title, card title, body text,
small label, overlay countdown, overlay role label. State explicitly whether the
numeral family has tabular figures.

Then **texture and effects**: what should be painted, and one line each on how it is
built from the primitives in §3. If the direction implies something in the
impossible list, say what you replaced it with and why.

**SECOND, and only after the table**, one image: a 1:1 mood board — the palette as
labelled swatches, a numerals specimen showing "4:23" "0:08" "READY" large, a few UI
fragments (a pill, a card corner, a progress ring, a hairline separator, a small
uppercase label), and a texture sample.

---

## §7 — TASKS 2 TO 11 · THE SURFACES

### TASK 2 — A cooldown in its six states *(the most useful image of all)*

A 1:1 component state sheet. The **same token** six times, in a two-row grid of
three, each labelled underneath:

1. **JUST CAST** — ring almost empty, "4:42", neutral
2. **HALFWAY** — ring about half closed, "2:34", neutral
3. **NEARLY BACK** — ring nearly closed, "0:24", warning colour
4. **READY** — ring fully closed, reads "READY", positive colour, plus whatever
   restrained emphasis the direction gives to "act on this now"
5. **UNCERTAIN** — same as 2, with a small circular "?" chip inside the bottom-right
   corner of the **spell badge**, not near the countdown
6. **ESTIMATE** — same as 2, countdown reads "~1:08", badge shows an ability rather
   than a summoner spell

*The six must be distinguishable without reading the labels. If "nearly back" and
"ready" read alike at a glance, the state colours are wrong.*

### TASK 3 — The chrono track, in play

16:9, simulated game background, the strip centred on the **top edge**, ~7:1
width-to-height. Rail with end ticks and a "ready"-tinted right sixth; four tokens
hanging below it joined by stems, placed at different points — one near the left, one
mid, two near the right; countdowns "4:42", "2:34", "0:24" (warning), "READY"
(positive). The strip is translucent: the scene must show faintly through it.

*The rail must stay visible over the brightest part of the scene, and the numerals
must hold without a halo.*

### TASK 4 — The fixed cards, in play

16:9, same background, a compact strip at the top centre, ~4.5:1. Five cards in one
evenly spaced row, role labels above, rings at five different stages (barely started,
a third, two thirds, nearly complete, complete), countdowns "4:42", "2:34", "1:08",
"0:24", "READY". This layout must read as a row of fixed instruments — nothing about
it slides.

*The ring thickness is the one delicate setting of this display: too thin it
disappears, too thick it eats the portrait. Offer two thicknesses if unsure.*

### TASK 5 — The compact rows, in play

3:2, same background, the panel along the **left** side, ~1:1.1. Six rows grouped
under role headings, each with portrait, badge, champion name in primary ink, spell
name in secondary ink, right-aligned countdown ("4:42", "0:47", "~1:08", "2:34",
"0:24" warning, "READY" positive), and a thin gauge along the row's bottom edge
filled to a different amount in that row's state colour. One row carries the "?"
chip on its badge.

### TASK 6 — At rest, and while being positioned

3:2, split into two clearly separated halves over the same background, each captioned
outside the strip.

- **AT REST** — the chrono track with nothing on cooldown: only its faint backing and
  bare rail, at very low opacity. Enough to see the app is alive and where it sits;
  no text, no tokens.
- **BEING POSITIONED** — the same strip unlocked: a visible outline in the warning
  colour, a short centred hint line inside it, and a resize grip in the bottom right
  as three diagonal hairlines.

*At rest is what the user sees 90% of the time. If it draws the eye it has failed;
if it is entirely invisible, nobody can tell the program is running.*

### TASK 7 — The bright-background test *(do not skip this one)*

16:9, the chrono track from TASK 3 unchanged, over a **bright** scene — pale,
sunlit, near-white in places. Keep the palette exactly as defined; do not compensate.

*This is the test that decided the current palette: a white countdown over a dark
translucent panel turns to grey-on-grey the moment the game is bright, at 3.56:1.
Light-and-opaque clears 10:1 on every background, which is why the product is light.
Your direction has to hold the same line. If it needs a stronger painted halo or a
more opaque backing, say so — both are buildable.*

### TASK 8 — The desktop window's component sheet

1:1, a tidy grid of isolated components on the window's ground, each captioned:
a **card** (title, secondary line, hairline) · a **primary**, a **ghost** and a
**danger** button at rest, plus the primary in hover and disabled · a **toggle
switch** in both states with a label · a closed **dropdown** showing a value · a
**number field** with a unit suffix ("200 ms") and stepper arrows · a **slider**
with filled portion and handle · four **state pills** in a row (neutral, positive,
warning, negative) · a **navigation column** fragment of four stacked entries with
one selected, the selection expressed in the direction's own vocabulary rather than a
plain filled rectangle · a collapsed **disclosure** row (small triangle, uppercase
label, hairline) · a **monospaced readout**, label left and tabular value right.

*Qt styles widgets one at a time, so this sheet is the image that translates most
directly into code. The switch and the state pill set the tone of the whole window:
if they look like any framework's defaults, the direction has not been pushed.*

### TASK 9 — The desktop window itself

Four images, one per message if you prefer.

**9a — HOME, 4:5.** Header (mark, name in the display face, tiny version number,
tagline underneath, state pill reading "IN GAME" in the positive colour on the far
right). Body split into the narrow navigation column, first entry selected, and a
content column of three cards: a status card (bold headline sentence, secondary
line, hairline, five label/value rows with tabular values); a card with a title, two
secondary lines and one primary button; a card with a title, two secondary lines, a
monospaced line inside an inset field and a small button beside it. Footer: a ghost
button left, a danger-styled button right.

**9b — DISPLAY, 4:5.** Same header and navigation, second entry selected. Content: a
card with a title, two secondary lines and one prominent primary button; then a card
holding **three selectable tiles stacked vertically**, each a wide rounded row with a
small schematic thumbnail on the left and a title plus two secondary lines on the
right. The thumbnails are (a) a horizontal rail with three small circles at different
positions, (b) three circles each wrapped in a partial progress ring, (c) three
stacked rows each with a small circle, two short text lines and a thin bar. The first
tile is selected, unmistakably. Then a position card with a heading, two secondary
lines and two buttons (one wide, one narrower under it), and a collapsed disclosure
row.

*Those thumbnails are 112×54 px in reality. If they only work large, show me a
magnified "thumbnails only" variant so I can see what survives the reduction.*

**9c — DENSE SURFACES, 3:2**, split in two: on the left a **settings** content column
(four cards holding between them a dropdown, five toggle switches, a number field
with a unit, a label/value row, one secondary button and two collapsed disclosure
rows); on the right a **troubleshooting** column (a paragraph of secondary text, a
card with three buttons in a small grid, a card with three stacked wide buttons, a
card with two inset read-only monospaced log areas each with a small caption above).
No header, no navigation, no footer — just the columns. *The point is density: eight
cards must still read as a calm, ordered page rather than a wall.*

**9d — THE UPDATE BANNER, 21:9.** A single notification strip as it appears at the
top of the window: a line of primary text announcing a new version, a second line of
secondary text reassuring about settings being kept, then three buttons in a row —
primary, secondary, and a quiet dismissive one on the far right. It must read as
"worth reading before whatever you opened this window for", without a saturated alert
bar.

### TASK 10 — The setup guide

**10a — THE FRAME, 4:5.** The wizard window: header (mark, title in the display face,
subtitle underneath, a small pill reading "STEP 2 OF 6" on the right); a large inset
**illustration panel** filling the upper half with a hairline border, holding a
placeholder schematic of a screen with a strip at its top edge; a step title, large;
a paragraph of two or three lines; a **note box** (inset panel, hairline, two quieter
lines); a footer with a six-dot step indicator with a connecting line and the second
dot active, a quiet text link far left, a secondary and a primary button right.

*Watch the ratio between figure and text. If the figure crushes the text nobody
reads; if it is timid, there was no point drawing it.*

**10b — THE SIX FIGURES, ONE SHEET, 1:1.** Six schematic diagrams in a two-by-three
grid, all sharing **one consistent diagrammatic language**, each in its own inset
rounded panel with a caption:

1. **WHAT IT DOES** — a simplified screen seen head-on; in its lower left a small
   framed chat box with three lines drawn as bars, one in the danger colour; along
   its top edge a small overlay strip with three circles on a rail; a dashed arrow
   rising from the chat box to the strip.
2. **WINDOW MODE** — a game's video-settings control: a small heading, three stacked
   option rows. First marked with a red cross and dimmed, second highlighted with a
   positive-colour tick, third neutral with an empty radio circle.
3. **CLIENT LANGUAGE** — two stacked message rows, each an inset panel holding one
   line of monospaced text whose first word is in the danger colour and the rest in
   primary ink. Upper row highlighted as selected with the accent, lower row dimmed,
   a tiny caption above each.
4. **CHAT AREA** — the same simplified screen, a rectangle in its lower left outlined
   in the positive colour, three short tick marks in the left margin just **outside**
   that rectangle, three text bars inside it, a small caption underneath.
5. **PLACING IT** — the same screen with a small strip at its top centre, four short
   arrows radiating from it, and a dashed ghost copy of the strip in the lower right
   with a caption.
6. **WHERE IT LIVES** — the bottom-right corner of a screen with a taskbar along the
   bottom; three small square icons near its right end, the leftmost circled in the
   accent colour, a dashed line rising from it to a two-line label.

Geometric shapes, flat fills, hairlines and dashes only. No isometric perspective, no
illustrative detail.

*Judge them side by side: same stroke weight, same way of drawing "a screen", same
arrows. That consistency is the only criterion here.*

**10c — THE STEP INDICATOR, 21:9.** Four genuinely different treatments of a
six-step indicator, stacked and captioned, current position always the second of six.
Not four variations of a dot row. Every one buildable from circles, rectangles, arcs
and hairlines.

### TASK 11 — The mark

**11a — CANDIDATES, 1:1.** Six candidate app marks in a two-by-three grid, each in a
square tile with a two-word caption naming its idea. What it must say, in order of
importance: a measured interval, an instrument, a watchful reading of something.
Abstract and geometric. **No** fantasy, gaming or medieval iconography, no eyes, no
swords, no runes, no crosshairs, no photographic stopwatch bezel. Each must be
describable purely as circles, arcs, straight segments and simple polygons — no
illustrative detail, no texture, no more than three colours.

**11b — THE SMALL-SIZE TEST, 16:9.** Take the two strongest candidates and show each
at 16, 24, 32 and 64 px, one row per candidate, at their **true relative
proportions** on a dark ground, size captioned under each. Do not simplify between
sizes and do not enlarge the small ones — the point is to see what collapses. Then
under each row, the same mark at 16 px inside a simulated Windows notification area:
a narrow taskbar strip with two other neutral square icons and a small clock.

*At 16 px the silhouette and one accent colour must be enough. A candidate that only
exists thanks to an interior detail is out, however beautiful it is large.*

**11c — THE GEOMETRY, AS NUMBERS.** For the chosen mark, on a 64×64 unit box, as a
plain numbered list — no prose, no SVG markup: every circle (centre, radius, fill,
stroke, stroke width) · every arc (centre, radius, start angle and sweep in degrees
counter-clockwise from three o'clock, stroke width, cap style) · every segment (both
endpoints, width, cap) · every polygon (points in order, fill) · the drawing order
back to front · which elements to **drop below 20 px** so the small version stays
clean.

*This is the format the code uses directly, so precision here saves a whole
round-trip.*

**11d — IN CONTEXT *(optional)*, 21:9.** Just the guide window's header strip, three
times, stacked, each with a different candidate mark on the left at its real size —
about a 34 px mark beside a 17 px title. Render the strips at their true relative
proportions and do not enlarge the marks: the point is to check the mark still reads
at that size next to text.

---

## §8 — TASK 12 · RESTYLE THE HTML MOCKUP

The human will attach `design/maquette/index.html` — a self-contained mockup of every
surface above, drawn in CSS. **Ask for it if it is not attached.** This is the highest
value task in the file: its output is exact values rather than an image to interpret.

**Change only** the tokens in the first `:root` block, the ones prefixed `--fw-`.
Their names map one-to-one onto constants in the app's source, so **do not rename,
remove or add any of them** — change their values. You may also adjust the small
number of rules that shape a component (a radius, a gradient direction, the weight of
a rule), provided every rule you touch stays buildable from the primitives in §3.

**Do not change** the second `:root` block, prefixed `--doc-` — that is the page's own
chrome and must stay readable whatever you do to the product. Do not change the HTML
structure, the class names, or the text content.

**Do not add** `backdrop-filter`, `box-shadow` on a widget, `transition`,
`transform`, a web-font URL, an external asset, or JavaScript.

**The test that matters:** section 03 of that page has a background switcher —
medium, dark, bright. Your palette must keep the countdown readable on **all three**.
The palette in the file already clears it; do not regress it for a prettier panel.

**Deliverable:** the complete modified file in one code block, ready to save over the
original. Then underneath, one line per decision on what you changed and why, and
explicitly name anything you compromised on because of §3.

---

## §8bis — TASK 13 · THE SIX ONBOARDING SCREENS

A six-screen first-run wizard whose whole premise is that **the user sets the app up
inside League's Practice Tool** rather than on an empty desktop: a real game window,
a real chat, a real interface scale, no teammates waiting, available on demand. Three
things cannot be verified anywhere else, and they are exactly the three that break
— does borderless actually work, is the chat area actually found, does the whole chain
actually produce a timer.

Same palette, type and chrome as TASK 10a throughout: a header with the mark, a
title, a subtitle and a step pill; a large inset illustration panel; a step title; a
paragraph; a note box; a footer with a six-dot indicator and back/next buttons.

**13a — WELCOME, 4:5.** Pill "STEP 1 OF 6". Inside the figure, a schematic of the
League client's play menu, flat geometry and NOT a screenshot: a rounded panel with
four game-mode rows, the fourth highlighted with the accent and an accent pointer,
labelled "Practice Tool". Above the list, two breadcrumb chips reading PLAY and
TRAINING joined by a chevron. The other three rows are dimmed and unlabelled. Beside
the highlighted row, a short accent caption: "no stakes, on demand".

**13b — WINDOW MODE, 4:5.** Pill "STEP 2 OF 6". A schematic RECREATION of League's
video setting, clearly a diagram rather than a capture of the real client: a
breadcrumb of three chips (a gear glyph, SETTINGS, VIDEO), then a settings row whose
label is "Window mode" and whose control shows three stacked options:

- Fullscreen — dimmed, a red cross in the danger colour, captioned "no overlay
  possible"
- Borderless — highlighted with the accent, ticked in the positive colour, captioned
  "pick this one"
- Windowed — neutral, an empty radio circle, no caption

A thin accent bracket draws the eye to the middle one. Use the client's own wording:
a player navigates this setting by matching words, so the words have to be right.

**13c — CLIENT LANGUAGE, 4:5.** Pill "STEP 3 OF 6". Two stacked inset message rows,
each holding one line of monospaced text whose first word is in the danger colour and
the rest in primary ink: "Ahri a utilise Saut eclair" above, captioned "French
client", and "Ahri used Flash" below, captioned "English client". The upper row is
selected with the accent, the lower one dimmed. Below the paragraph, a real closed
dropdown showing a language.

**13d — PICKING A DISPLAY, 16:9, split composition.** LEFT THIRD: the wizard,
narrower, pill "STEP 4 OF 6", holding three selectable tiles stacked vertically. Each
tile is a wide rounded row with a small schematic thumbnail on the left — a rail with
three circles / three circles each wrapped in a partial ring / three stacked rows
with a thin bar — and a title plus one secondary line on the right. The SECOND tile is
selected, unmistakably. RIGHT TWO THIRDS: a simulated Practice Tool screen with a
plain chat box in its lower left and, along its top centre, the display matching the
selected tile — the fixed cards, five of them, with role labels, portraits carrying
closing rings, spell badges, and the countdowns 4:42, 2:34, 1:08, 0:24 in the warning
colour and READY in the positive one. Draw a soft accent connector from the selected
tile to the overlay: choosing it here puts it there, immediately.

**13e — PLACING IT, 16:9.** The Practice Tool screen fills the frame; a compact
wizard panel docks in the lower left, pill "STEP 5 OF 6", one line of text, one
primary button reading "Done, lock it". On the game screen: the chosen display near
the top centre, outlined in the warning colour to say it is unlocked, with a resize
grip of three diagonal hairlines in its corner, four short accent arrows radiating
from it, and a dashed ghost copy of it in the upper right captioned "or anywhere
else", linked to it by a faint dashed path.

**13f — THE PROOF, 16:9.** The same screen, wizard docked lower left, pill "STEP 6 OF
6", holding an inset monospaced field with the line "Wait Darius Flash - 245 sec." and
a small button beside it reading "Copy". On the game screen: the chat box open in the
lower left showing three lines, the newest being that same sentence in the player's
own text colour; the overlay along the top centre holding exactly **one** cooldown —
a portrait, its badge, and the countdown 4:05; and a dashed accent arrow rising from
the chat line to it, captioned "read off the screen".

*One cooldown, not five. This screen exists to show a single cause producing a single
effect, and five would lose it.*

The seventh beat — where the program lives afterwards, its icon in the notification
area — is already TASK 10b's sixth figure. Do not redraw it.

## §9 — WHAT HAPPENS TO YOUR ANSWERS

Another assistant will port your work into the app's Qt source: the token table
becomes constants in `theme.py`, the state sheet becomes the overlay's painting code,
the six figures become `QPainter` calls, the mark's geometry becomes a handful of
numbers drawn by two different renderers.

So **precision beats prose**. "A warm grey" costs a round-trip; `#2a2622` does not.
An image is an intention; a hex value is a decision. When you are unsure whether
something is buildable, say so and give the fallback rather than quietly hoping.

---

## §10 — YOUR FIRST REPLY

Do not generate anything yet. Reply with, and only with:

1. Three lines confirming you have the brief: what the product is, what the hardest
   constraint is, and which task gates the others.
2. The five directions as a numbered list, one line each, in your own words.
3. Your own recommendation — which direction you would pick for *this* product and
   why, in two sentences.
4. The question: which direction, and shall we start with TASK 1.

Then stop and wait.
