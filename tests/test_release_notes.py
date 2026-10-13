# -*- coding: utf-8 -*-
"""The release notes: what a player reads on the download page.

Two promises the script makes and once broke: a ``[skip release]`` commit is not
news on the release that eventually ships, and the bump markers count anywhere
in a commit message -- the body included, not just the subject.
"""
import sys, io, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import release_meta  # noqa: E402

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


commits = [
    ("Show the enemy team the way the game does", "Long body.\n\n[major]"),
    ("Keep the Vercel token out of the repository [skip release]", ""),
    ("Print the disclaimer at the foot of the page", "Site only. [skip release]"),
    ("wip", ""),
    ("Time each enemy for that enemy [minor]", ""),
]
notes = release_meta.format_notes("2.0.0", commits, "v1.0.3", highlights="")
check("a program change is listed",
      "- Show the enemy team the way the game does" in notes)
check("a [skip release] subject is left out", "Vercel" not in notes)
check("a [skip release] body is left out too", "disclaimer" not in notes)
check("noise is left out", "- wip" not in notes)
check("markers are stripped from what is shown",
      "- Time each enemy for that enemy\n" in notes and "[minor]" not in notes)
check("the notes open in English", notes.startswith("## What's new"))
check("and the install steps are given in French as well",
      "En français" in notes and "Exécuter quand même" in notes)
check("the previous version is named", "`v1.0.3`" in notes)

check("a [major] in a body counts", release_meta.decide_bump(commits, None) == "major")
check("a [minor] in a subject counts",
      release_meta.decide_bump(commits[4:], None) == "minor")
check("no marker is a patch", release_meta.decide_bump([("Fix", "")], None) == "patch")
check("--bump overrides", release_meta.decide_bump(commits, "patch") == "patch")
check("bare subjects are still accepted",
      release_meta.decide_bump(["Thing [minor]"], None) == "minor")

with tempfile.TemporaryDirectory() as folder:
    directory = Path(folder)
    (directory / "v2.0.0.md").write_text("## Highlights\n\nThe overhaul.\n", "utf-8")
    check("a version's highlights are found", release_meta.highlights_for(
        "2.0.0", directory).startswith("## Highlights"))
    check("another version has none", release_meta.highlights_for("2.0.1", directory) == "")
with_highlights = release_meta.format_notes(
    "2.0.0", commits, None, highlights="## Highlights\n\nThe overhaul.")
check("highlights lead the notes", with_highlights.startswith("## Highlights"))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
