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
