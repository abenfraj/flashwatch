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

The site is **https://flashwatch.app**, served by Netlify and published by its
CLI -- pushing `main` ships the application, never the page.
`flashwatch.vercel.app` only answers with 308 redirects (`vercel.json`).

Never deploy this folder itself: it holds `.env.local` and `.vercel/`. Copy the
public files to a clean folder and deploy that:

```powershell
python tools/make_seo.py        # if the FAQ changed: rewrites the JSON-LD
$dist = "C:/Users/ayoub/dev/flashwatch-site-dist"
Remove-Item -Recurse -Force $dist -ErrorAction SilentlyContinue
New-Item -ItemType Directory $dist | Out-Null
Copy-Item site/index.html, site/favicon.ico, site/apple-touch-icon.png, site/logo.png, site/logo-96.png, site/hero-champions.jpg, site/og-image.jpg, site/robots.txt, site/sitemap.xml, site/google22ae7561f6dcbe2b.html $dist
Copy-Item -Recurse site/img $dist/img
netlify deploy --prod --no-build --dir $dist
```

**`img/` is part of the page.** Every champion portrait and spell icon the page
draws is a file in it; the page never asks Riot's CDN for anything. Forget the
folder and every icon on the live site is a broken image.

## The icons: why they are files here

They used to be hotlinked from Data Dragon at load time, after asking it for its
latest version. That made the first screen depend on somebody else's server, on
a second request succeeding, and on nothing between the visitor and that server
(an ad blocker, a corporate proxy, a DNS filter) taking a dislike to it -- any of
which leaves the demo as empty circles. They are now 96 px WebP copies of the
icons the program itself caches (`assets/cache/`), about 50 KB for all of them,
written straight into the markup so they show even before the script runs.

To add one, convert it from the program's cache into `img/champion/` or
`img/spell/` (champions at 96 px, spells at their native 64 px, WebP).

## Two languages, one copy of the text

The page is written in English and translated to French at runtime; the switch
sits in the top bar, next to the download button rather than inside `.topnav`,
which is hidden below 900 px.

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

- the hero: a stand-in for your screen, with the **team display** -- the
  program's default -- at its right edge, drawn after `src/overlay.py`: the
  countdown astride each spell's bottom edge, the light dim, the clockwise
  wedge, amber under fifteen seconds, the green ring for five seconds when a
  spell is back, faint rows for enemies with nothing down. A thirty-second
  script at real speed, with the chat lines that start each timer;
- fair play: what it never does and the only things it does;
- features, each card with a working miniature: a switcher that redraws the
  same simulated game as the team, track, cards and rows displays; per-enemy
  haste; the game-mode switches; click-through; sounds; CPU;
- how it works in three steps, and the cooldown table with haste toggles
  (`cooldown x 100 / (100 + haste)`, the values in `src/cooldowns.py`);
- installation, the two settings that are not optional, the latest release's
  notes and every version, read from GitHub at load time;
- the FAQ -- its `<details>` are what `tools/make_seo.py` turns into JSON-LD, so
  keep `<section id="faq">`, bare `<summary>` and `<div class="a">`;
- Riot's disclaimer, in full, in the footer.

The old section anchors (`#securite`, `#fonctionnement`, `#displays`,
`#config`, `#versions`, `#rules`) still exist, so links already out there land.
`?lang=fr` opens the page in French.

Motion respects `prefers-reduced-motion`: the demo then holds one moment instead
of ticking. The clock runs only while a demo is on screen.

Colours are the program's own (`src/theme.py`'s navy and violet; the overlay's
white, amber and green inside the widgets). Fonts come from Google Fonts --
Barlow Semi Condensed for headlines and every number, standing in for the
overlay's Bahnschrift, and Mulish, the settings window's face, for text.

## Checking it

Never open it on screen: headless Edge, PNG captures. Headless Edge lays a page
out at no less than about 500 px whatever `--window-size` says, so a phone-width
capture goes through a wrapper page holding a 390 px iframe. Measure
`document.documentElement.scrollWidth` against `clientWidth` before believing a
narrow screenshot.
