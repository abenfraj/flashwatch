# -*- coding: utf-8 -*-
"""Write the site's robots.txt, sitemap.xml and structured data.

Run after changing the page::

    python tools/make_seo.py

The structured data is **read out of the page** rather than typed here. A search
engine that finds an answer in the markup and a different one in the JSON-LD is
entitled to distrust both, and a hand-kept copy of seven FAQ answers drifts from
the page the first time one of them is edited. So the FAQ block is extracted from
the ``<details>`` elements it describes, and regenerated whenever they change.

The JSON goes between two markers in ``index.html`` and replaces whatever was
there, so running this twice does not stack two copies.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "site" / "index.html"
SITE = "https://flashwatch.vercel.app"

BEGIN = "<!-- structured-data:begin -->"
END = "<!-- structured-data:end -->"

# The first entry is <details open> -- it is the one the page shows unfolded --
# so the attribute is optional here. Requiring a bare <details> silently dropped
# it, which is the failure mode this whole file exists to avoid.
FAQ_RE = re.compile(
    r"<details[^>]*>\s*<summary>(?P<q>.*?)</summary>\s*"
    r'<div class="a">(?P<a>.*?)</div>', re.S)


def text_of(html: str) -> str:
    """Markup to the sentence a human would read out of it."""
    plain = re.sub(r"<[^>]+>", "", html)
    return unescape(re.sub(r"\s+", " ", plain)).strip()


def latest_tag() -> str:
    try:
        done = subprocess.run(["git", "tag", "--list", "v*", "--sort=-v:refname"],
                              cwd=ROOT, text=True, capture_output=True, check=True)
        tags = [line for line in done.stdout.splitlines() if line]
        return tags[0].lstrip("v") if tags else "1.0.0"
    except Exception:                                 # noqa: BLE001
        return "1.0.0"


def faq_entries(page: str) -> list[dict]:
    section = page[page.index('<section id="faq">'):]
    section = section[:section.index("</section>")]
    return [{"@type": "Question",
             "name": text_of(match.group("q")),
             "acceptedAnswer": {"@type": "Answer",
                                "text": text_of(match.group("a"))}}
            for match in FAQ_RE.finditer(section)]


def blocks(page: str) -> list[dict]:
    """What the page is, and what it answers.

    Two objects and no more. The application one is what a "download" result
    hangs off -- a price of zero is a fact worth stating, since "free" is the
    question every one of these pages is really being asked -- and the FAQ one is
    the only part of this page eligible for a rich result.
    """
    return [
        {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": "Flashwatch",
            "url": f"{SITE}/",
            "applicationCategory": "GameApplication",
            "applicationSubCategory": "League of Legends overlay",
            "operatingSystem": "Windows 10, Windows 11",
            "softwareVersion": latest_tag(),
            "downloadUrl":
                "https://github.com/abenfraj/flashwatch/releases/latest",
            "installUrl": f"{SITE}/#install",
            "screenshot": f"{SITE}/og-image.jpg",
            "image": f"{SITE}/logo.png",
            "inLanguage": ["en", "fr"],
            "isAccessibleForFree": True,
            "offers": {"@type": "Offer", "price": "0",
                       "priceCurrency": "EUR"},
            "author": {"@type": "Person", "name": "abenfraj",
                       "url": "https://github.com/abenfraj"},
            "description":
                "A free Windows overlay for League of Legends that tracks enemy "
                "summoner spell and ultimate cooldowns by reading the match "
                "chat on screen. No installation, no injection, no memory "
                "reading and nothing to press during a game.",
        },
        {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": faq_entries(page),
        },
    ]


def main() -> int:
    page = PAGE.read_text(encoding="utf-8")

    payload = "\n".join(
        f'<script type="application/ld+json">\n'
        f'{json.dumps(block, ensure_ascii=False, indent=2)}\n</script>'
        for block in blocks(page))
    replacement = f"{BEGIN}\n{payload}\n{END}"

    if BEGIN in page and END in page:
        page = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END),
                      lambda _: replacement, page, flags=re.S)
    else:
        # First run: in the head, after the social tags.
        page = page.replace("</head>", replacement + "\n</head>", 1)
    PAGE.write_text(page, encoding="utf-8")

    (ROOT / "site" / "robots.txt").write_text(
        "# Everything here is meant to be found.\n"
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {SITE}/sitemap.xml\n", encoding="utf-8")

    (ROOT / "site" / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url>\n"
        f"    <loc>{SITE}/</loc>\n"
        "    <changefreq>weekly</changefreq>\n"
        "    <priority>1.0</priority>\n"
        "  </url>\n"
        "</urlset>\n", encoding="utf-8")

    faq = len(blocks(page)[1]["mainEntity"])
    print(f"index.html  structured data for {faq} FAQ answers, "
          f"version {latest_tag()}")
    print("robots.txt  written")
    print("sitemap.xml written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
