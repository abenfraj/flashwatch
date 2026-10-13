"""Work out the next version and write the patch notes.

Run by the release workflow, but deliberately a plain script rather than YAML: the
version arithmetic and the note formatting are the parts most likely to be wrong,
and this way they can be run and read on a laptop.

    python tools/release_meta.py                 # print what the next release
                                                 # would be, change nothing
    python tools/release_meta.py --write         # stamp src/version.py, write
                                                 # RELEASE_NOTES.md, and emit the
                                                 # version to GITHUB_OUTPUT

How the number moves: the newest ``vX.Y.Z`` tag, bumped by one. Patch by default;
minor or major if the range of commits says so -- ``[minor]`` or ``[major]``
anywhere in a commit message, which is the lightest convention that still lets a
notable change announce itself. ``--bump`` overrides everything, for a manual run.

What the notes say: the subject of every commit in the range that changed the
program. A commit marked ``[skip release]`` changed the site, the docs or the
workflow -- it is why no release was cut for it -- so it is not news on the
release that eventually ships, and is left out. A version can also carry a
hand-written summary for players, in ``.github/highlights/vX.Y.Z.md``; when the
file for the version being cut exists, it leads the notes.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# The notes are French and contain arrows and accents; a Windows console defaults
# to cp1252 and would raise rather than print them.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "src" / "version.py"
NOTES_FILE = ROOT / "RELEASE_NOTES.md"
HIGHLIGHTS_DIR = ROOT / ".github" / "highlights"

FIRST_VERSION = (0, 1, 0)
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

# Commits that say nothing to a user reading a release page.
BORING = re.compile(
    r"^(merge |wip\b|fixup|amend|typo\b|formatting\b|reformat|lint\b|"
    r"bump version|release v?\d)", re.IGNORECASE)


def git(*args: str) -> str:
    """Run git and return stdout, or "" if the command fails."""
    try:
        done = subprocess.run(("git",) + args, cwd=ROOT, text=True,
                              capture_output=True, check=True,
                              encoding="utf-8", errors="replace")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    return done.stdout.strip()


def latest_tag() -> tuple[str, tuple[int, int, int]] | tuple[None, None]:
    """Newest release tag, by version order rather than by date."""
    tags = [line for line in git("tag", "--list", "v*").splitlines() if line]
    parsed = []
    for tag in tags:
        match = TAG_RE.match(tag.strip())
        if match:
            parsed.append((tuple(int(p) for p in match.groups()), tag.strip()))
    if not parsed:
        return None, None
    parsed.sort()
    version, tag = parsed[-1]
    return tag, version


def commits_since(tag: str | None) -> list[tuple[str, str]]:
    """``(subject, body)`` since ``tag``, newest first, merges left out.

    Bodies as well as subjects, because both conventions this script honours --
    the bump markers and ``[skip release]`` -- are promised to work anywhere in
    a commit message, and a subject-only read quietly broke that promise.
    """
    span = f"{tag}..HEAD" if tag else "HEAD"
    raw = git("log", span, "--no-merges", "--pretty=format:%s%x1f%b%x1e")
    commits = []
    for record in raw.split("\x1e"):
        if not record.strip():
            continue
        subject, _sep, body = record.strip("\n").partition("\x1f")
        if subject.strip():
            commits.append((subject.strip(), body.strip()))
    return commits


def _pairs(commits):
    """Accept ``(subject, body)`` pairs or bare subjects, for older callers."""
    for commit in commits:
        if isinstance(commit, tuple):
            yield commit
        else:
            yield commit, ""


def decide_bump(commits, forced: str | None) -> str:
    if forced:
        return forced
    blob = " \n".join(f"{subject}\n{body}"
                      for subject, body in _pairs(commits)).lower()
    if "[major]" in blob:
        return "major"
    if "[minor]" in blob:
        return "minor"
    return "patch"


def next_version(current: tuple[int, int, int] | None, bump: str) -> tuple[int, int, int]:
    if current is None:
        return FIRST_VERSION
    major, minor, patch = current
    if bump == "major":
        return (major + 1, 0, 0)
    if bump == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


SKIP_MARK = re.compile(r"\[skip release\]", re.IGNORECASE)


def news(commits) -> list[str]:
    """The subjects worth a line on the release page."""
    lines = []
    for subject, body in _pairs(commits):
        if SKIP_MARK.search(subject) or SKIP_MARK.search(body):
            # The site, the docs, the workflow: not the program being released.
            continue
        if BORING.match(subject):
            continue
        # Strip the markers: they are instructions to the workflow and to this
        # script, not news.
        lines.append(re.sub(r"\s*\[(minor|major)\]\s*", " ", subject,
                            flags=re.I).strip())
    return lines


def highlights_for(version: str, directory: Path = HIGHLIGHTS_DIR) -> str:
    try:
        return (directory / f"v{version}.md").read_text("utf-8").strip()
    except OSError:
        return ""


def format_notes(version: str, commits, previous: str | None, *,
                 highlights: str | None = None) -> str:
    """The release body, as a user reading the download page will see it.

    English first: the download page opens in English, and GitHub's own release
    page is read from everywhere. The install steps follow in French too,
    shorter, for the players the program speaks French to.
    """
    if highlights is None:
        highlights = highlights_for(version)
    lines: list[str] = []
    if highlights:
        lines += [highlights, ""]

    lines.append("## What's new")
    changes = news(commits)
    if changes:
        lines += [f"- {change}" for change in changes]
    else:
        lines.append("- Internal fixes, nothing visible changed.")

    lines += [
        "",
        "## Install",
        "",
        "**Already have Flashwatch?** Nothing to download: start it and it offers "
        "the update itself (banner at the top of its window), then replaces its "
        "own executable. Your settings are kept.",
        "",
        "**First install:** download `Flashwatch.exe` below, put it in a folder of "
        "its own and double-click it. Windows says \"Windows protected your PC\" "
        "because the file is not signed: *More info* -> *Run anyway*. Internet is "
        "needed on the first launch, for the champion icons.",
        "",
        "**En français :** déjà installé, lancez-le et acceptez la mise à jour "
        "proposée. Sinon, téléchargez `Flashwatch.exe`, placez-le dans son propre "
        "dossier et double-cliquez (*Informations complémentaires* -> *Exécuter "
        "quand même*).",
    ]
    if previous:
        lines += ["", "---", "", f"Previous version: `{previous}`."]
    return "\n".join(lines) + "\n"


def stamp_version(version: str) -> None:
    text = VERSION_FILE.read_text(encoding="utf-8")
    stamped, count = re.subn(r'^__version__ = ".*"$',
                             f'__version__ = "{version}"', text,
                             flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"could not stamp {VERSION_FILE}: "
                         f"{count} occurrences of __version__")
    VERSION_FILE.write_text(stamped, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="stamp the version file and write the notes")
    parser.add_argument("--bump", choices=("patch", "minor", "major"),
                        help="force the size of the bump")
    args = parser.parse_args()

    tag, current = latest_tag()
    commits = commits_since(tag)
    bump = decide_bump(commits, args.bump)
    version = ".".join(str(p) for p in next_version(current, bump))
    notes = format_notes(version, commits, tag)

    print(f"previous tag : {tag or '(none)'}")
    print(f"commits      : {len(commits)}")
    print(f"bump         : {bump}")
    print(f"next version : v{version}")

    if not args.write:
        print("\n--- notes preview " + "-" * 52)
        print(notes)
        return 0

    stamp_version(version)
    NOTES_FILE.write_text(notes, encoding="utf-8")
    print(f"stamped {VERSION_FILE.relative_to(ROOT)} and wrote "
          f"{NOTES_FILE.relative_to(ROOT)}")

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"version={version}\n")
            handle.write(f"tag=v{version}\n")
            handle.write(f"previous={tag or ''}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
