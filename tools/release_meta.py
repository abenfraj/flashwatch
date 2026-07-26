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


def commits_since(tag: str | None) -> list[str]:
    """Subject lines since ``tag``, newest first, merges left out."""
    span = f"{tag}..HEAD" if tag else "HEAD"
    raw = git("log", span, "--no-merges", "--pretty=format:%s")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def decide_bump(commits: list[str], forced: str | None) -> str:
    if forced:
        return forced
    blob = " \n".join(commits).lower()
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


def format_notes(version: str, commits: list[str], previous: str | None) -> str:
    """The release body, as a user reading the download page will see it."""
    interesting = [c for c in commits if not BORING.match(c)]
    # Strip the bump markers: they are instructions to this script, not news.
    interesting = [re.sub(r"\s*\[(minor|major)\]\s*", " ", c, flags=re.I).strip()
                   for c in interesting]

    lines = ["## Nouveautés"]
    if interesting:
        lines += [f"- {c}" for c in interesting]
    else:
        lines.append("- Corrections internes, aucun changement visible.")

    lines += [
        "",
        "## Installation",
        "",
        "**Vous avez déjà Flashwatch ?** Ne retéléchargez rien : lancez-le, il "
        "propose la mise à jour tout seul (bandeau en haut de la fenêtre de "
        "réglages) et remplace son propre exécutable. Vos réglages sont conservés.",
        "",
        "**Première installation :** téléchargez `Flashwatch.exe` ci-dessous, "
        "placez-le dans son propre dossier et double-cliquez.",
        "",
        "Windows affichera « Windows a protégé votre PC » : *Informations "
        "complémentaires* → *Exécuter quand même*. L'exécutable n'est pas signé, "
        "c'est tout ce que cet avertissement signifie.",
        "",
        "Rien ne s'ouvre à l'écran : l'icône apparaît dans la zone de "
        "notification, en bas à droite. Internet est nécessaire au premier "
        "lancement (téléchargement des icônes de champions).",
        "",
        "Vos réglages sont conservés : ils vivent dans le dossier `assets` créé à "
        "côté de l'exécutable, pas dans le fichier lui-même.",
    ]
    if previous:
        lines += ["", "---", "",
                  f"Version précédente : `{previous}`."]
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
