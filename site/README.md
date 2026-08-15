# site/

The download page. One `index.html`, no build step, no dependencies, no backend —
drop it on any static host.

## Before publishing: one line

Open `index.html`, find `GITHUB_USER` near the bottom (in the script block) and put
your GitHub account in:

```js
const GITHUB_USER = "ton-pseudo";
const GITHUB_REPO = "flashwatch";
const FILE_NAME  = "Flashwatch.exe";
```

Every download button on the page is built from those three, and points at
`releases/latest/download/Flashwatch.exe` — the URL GitHub keeps aimed at your newest
release. Publish a new release and the page needs no change.

## The social card, and why its URL carries a version

`og-image.jpg` is what Discord, Slack and the rest unfurl. It is drawn by
`tools/make_og.py` from the hero artwork, the logo and the champion icons the
program has already downloaded, at 1200 x 630 -- the size every scraper expects.

Two things about it are easy to get wrong, and both cost a day to notice:

**The URLs in the meta tags must be absolute.** A scraper reads the markup on its
own and has no page to resolve `og-image.jpg` against, so a relative one is
dropped and the link unfurls as plain text.

**Discord caches embeds, and it caches them hard.** The cache is keyed on the
exact URL string and ignores `Cache-Control` -- which this host already serves as
`max-age=0, must-revalidate`. So after fixing anything about the card:

* a URL Discord has never seen shows the new card immediately. `?v=2`, or
  `/index.html`, or a trailing slash where there was none: all different keys;
* the URL it *has* seen goes on showing the old embed until its entry expires by
  itself, usually within a day. There is no way to purge it -- no endpoint, no
  header, nothing this repository can serve;
* the **image** is proxied and cached by URL too, so a redrawn card under the
  same filename keeps unfurling as the old picture. That is what the `?v=` on the
  `og:image` tag is for. Bump it whenever the card is redrawn.

## Where the 98 MB file goes: not here

Put the binary in a **GitHub release**, not in this folder. Release assets are
capped at 2 GiB with no bandwidth limit, while Vercel's Hobby plan refuses a
deployment over 100 MB of source files and counts every download against 100 GB of
monthly transfer.

1. Push the repository to GitHub (the `.exe` is *not* committed).
2. *Releases* → *Draft a new release* → drag `dist\Flashwatch.exe` in → publish.
3. Deploy this folder. The page itself is a few tens of KB.

## Deploying

```bash
npx vercel deploy --prod site          # or: point a Vercel project at site/
```

Any static host works the same way — Cloudflare Pages, Netlify, GitHub Pages.

## Checking it

Open `index.html` in a browser; there is nothing to compile. The page was checked
at 1440 px and at 500 px wide, with a headless Chromium, in its
`prefers-reduced-motion` state as well as the animated one.

A note on that: Chromium headless has a minimum window width of about 492 px, so a
`--window-size=420` screenshot renders a wider page and crops it, which looks
exactly like a broken responsive layout. Measure `document.documentElement.scrollWidth`
against `clientWidth` before believing a screenshot.

## Two languages, one copy of the text

The page is written in English and translated to French at runtime; the switch
sits in the top bar, next to the download button rather than inside `.topnav`,
which is hidden below 880 px.

Only the French strings are stored, in the `FR` object at the top of the script.
The English is read out of the markup itself at load, so there is no second copy
of the page to fall out of step with it — edit the HTML and the English is
already correct. A block with inline markup (the `<pre>` diagram, the settings
mock-up, the FAQ) carries one key on its container and is swapped whole, so the
two languages are free to differ in shape.

The choice is remembered in `localStorage`; English is the default. The `og:` and
`description` meta tags stay English on purpose: crawlers read the static HTML
and never press the button.

Adding a string means adding `data-i18n="some.key"` in the markup and one entry
to `FR`. Nothing else — and if you forget the entry, the block simply stays in
English rather than breaking.

## What is in the page

- the hero, with a **live mock of the overlay**: the markers really do ride the
  track as their cooldowns run down, show `READY` for five seconds and disappear,
  using the same left-to-right placement and the same anti-overlap pass as the
  application;
- installation in three steps, SmartScreen included, since that is where a
  first-time user gets stuck;
- configuration, with the two settings that are not optional (client language,
  borderless windowed) called out as such;
- where the timers come from — the `a utilisé` / `used` announcement the game
  prints for enemies only — plus the line to type by hand to test the OCR;
- what the program never does (injection, memory, inputs, game servers);
- a FAQ covering the antivirus warning, nothing showing up, CPU cost, where the
  settings live.

Colours, hairlines and monospace readouts are taken from the overlay's own dark
theme, so the page and the tool look like the same object. Fonts come from Google
Fonts (Chakra Petch, Barlow, JetBrains Mono) — the only external request on the
page.
