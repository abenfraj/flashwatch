"""Finding, fetching and installing a newer build.

Flashwatch ships as a single portable .exe, which is what makes updating it both
easy and easy to get wrong. Downloading a new one from the browser leaves the old
one sitting next to it, so a few releases in there is a pile of
``Flashwatch (3).exe`` and no way to tell which is current. Updating from inside
the program instead means there is only ever one executable, and it is the newest
one.

**Replacing a running executable.** Windows will not let anything overwrite or
delete the image of a running process, but it *will* let it be renamed. So the
swap is three renames on the same directory, none of which can leave the user
without a program:

    Flashwatch.exe        -> Flashwatch.previous.exe    (still running, fine)
    Flashwatch.new.exe    -> Flashwatch.exe             (the download)
    (next start-up)          Flashwatch.previous.exe deleted

Renames rather than copies, so nothing is half-written: each step either happened
or it did not. If the second one fails the first is undone, and the user is left
with exactly what they started with.

Settings and the icon cache live in ``assets`` beside the executable rather than
inside it, so replacing the file keeps everything the user has configured. The
other way people update -- downloading the .exe and running it from a new folder
-- has nothing to do with this module and is handled at start-up by
:func:`settings.carry_config_forward`.

Deliberately Qt-free: the network and the file swap are the parts worth testing,
and they are testable only if importing this does not need a running application.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

log = logging.getLogger(__name__)

OWNER = "abenfraj"
REPO = "flashwatch"
# The name the release workflow attaches, and the name the running copy has.
ASSET_NAME = "Flashwatch.exe"

API_LATEST = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{OWNER}/{REPO}/releases"

REQUEST_TIMEOUT = 15
# Generous: this is 80-odd megabytes over whatever connection the user has, and a
# stall matters more than a slow line. requests applies it per socket operation,
# not to the whole transfer, so a slow download is never cut off.
DOWNLOAD_TIMEOUT = 60
CHUNK_BYTES = 256 * 1024

# A bundle carrying Qt, OpenCV and the OCR models cannot plausibly be smaller.
# The release workflow refuses to publish anything under 60 MB; this is the same
# guard on the receiving side, so a captive-portal HTML page or a truncated
# transfer can never be renamed over a working executable.
MIN_PLAUSIBLE_BYTES = 40 * 1024 * 1024

VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")

# Suffixes used during the swap. Both are cleaned up on the next start-up.
STAGED_NAME = "Flashwatch.new.exe"
BACKUP_NAME = "Flashwatch.previous.exe"


class UpdateError(Exception):
    """Anything that stopped an update, with a message fit to show the user."""


@dataclass(slots=True)
class Release:
    """A published release worth offering."""

    version: str
    tag: str
    notes: str
    download_url: str
    size: int
    page_url: str


def parse_version(text: str) -> tuple[int, int, int] | None:
    """Pull ``(major, minor, patch)`` out of a version or tag string.

    Tolerant on purpose: the tag is ``v1.2.3`` and the stamped version is
    ``1.2.3``, and a comparison that cared about the ``v`` would silently never
    find an update.
    """
    match = VERSION_RE.search(str(text or ""))
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())     # type: ignore[return-value]


def is_newer(candidate: str, current: str) -> bool:
    """Whether ``candidate`` is a later version than ``current``.

    Unparseable on either side means "no". Running from source the version is the
    ``0.0.0-dev`` placeholder, which parses as ``(0, 0, 0)`` and is older than
    every release -- correct in principle, but :func:`installed_exe` is what
    actually stops a working copy being offered an update it cannot apply.
    """
    left, right = parse_version(candidate), parse_version(current)
    if left is None or right is None:
        return False
    return left > right


def installed_exe() -> Path | None:
    """The executable to replace, or None when there is nothing replaceable.

    None running from source: there is no packaged build to swap, and the answer
    to "your checkout is out of date" is git, not a download.
    """
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve()


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "flashwatch-updater",
        "Accept": "application/vnd.github+json",
    })
    return session


def fetch_latest(*, session: requests.Session | None = None) -> Release | None:
    """The newest published release, whether or not it is newer than this build.

    None means the *lookup* failed -- no network, a rate-limited API, a release
    with no binary attached. Deliberately not the same answer as "nothing newer":
    the on-demand check in the settings has to tell those apart, because "you are
    up to date" and "GitHub did not answer" call for different words.

    Never raises. An automatic check is something the user did not ask for, so a
    failure belongs in the log and nowhere else.
    """
    own = session is None
    session = session or _session()
    try:
        response = session.get(API_LATEST, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        log.info("update check failed (%s)", exc)
        return None
    finally:
        if own:
            session.close()

    if not isinstance(payload, dict) or payload.get("draft"):
        return None

    tag = str(payload.get("tag_name") or "")
    version = ".".join(str(part) for part in (parse_version(tag) or ()))
    if not version:
        log.info("latest release has no usable version (%r)", tag)
        return None

    asset = next((a for a in payload.get("assets") or []
                  if str(a.get("name")) == ASSET_NAME), None)
    if asset is None or not asset.get("browser_download_url"):
        # A release with no binary is nothing the user can install; pointing them
        # at it would be worse than staying quiet.
        log.warning("release %s has no %s asset", tag, ASSET_NAME)
        return None

    return Release(
        version=version,
        tag=tag,
        notes=str(payload.get("body") or ""),
        download_url=str(asset["browser_download_url"]),
        size=int(asset.get("size") or 0),
        page_url=str(payload.get("html_url") or RELEASES_PAGE),
    )


def check(current_version: str, *, session: requests.Session | None = None
          ) -> Release | None:
    """The latest release if it is newer than ``current_version``, else None.

    What the automatic start-up check calls: one answer, and nothing to report
    unless there is something to install.
    """
    release = fetch_latest(session=session)
    if release is None:
        return None
    if not is_newer(release.version, current_version):
        log.info("up to date (running %s, latest %s)", current_version,
                 release.version)
        return None
    return release


def staged_path(target: Path) -> Path:
    """Where the download lands.

    Beside the executable, not in the temp directory: the install is a rename,
    and a rename cannot cross volumes. Staging on ``C:`` for a program running
    from a USB stick would turn the atomic step into a copy at the worst possible
    moment.
    """
    return target.with_name(STAGED_NAME)


def backup_path(target: Path) -> Path:
    return target.with_name(BACKUP_NAME)


def can_install(target: Path) -> bool:
    """Whether the executable's own directory can be written to.

    Checked before offering the update rather than after downloading 80 MB. A
    copy in Program Files fails here, and the honest answer for that case is the
    download page.
    """
    probe = target.with_name(".flashwatch-update-test")
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError as exc:
        log.info("cannot write next to %s (%s)", target, exc)
        return False


def download(release: Release, destination: Path,
             progress: Callable[[int, int], None] | None = None,
             *, cancelled: Callable[[], bool] | None = None,
             session: requests.Session | None = None) -> Path:
    """Fetch the new executable to ``destination``, then check it is one.

    The checks are the reason this is not three lines: whatever ends up here is
    about to be renamed over the program the user runs, so "the transfer did not
    raise" is not enough. A truncated download, a proxy's sign-in page and a
    rate-limit response all arrive as a perfectly successful HTTP 200.
    """
    own = session is None
    session = session or _session()
    partial = destination.with_name(destination.name + ".part")
    try:
        partial.unlink(missing_ok=True)
        with session.get(release.download_url, stream=True,
                         timeout=DOWNLOAD_TIMEOUT) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or release.size or 0)
            done = 0
            with open(partial, "wb") as handle:
                for chunk in response.iter_content(CHUNK_BYTES):
                    if cancelled is not None and cancelled():
                        raise UpdateError("cancelled")
                    if not chunk:
                        continue
                    handle.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
    except requests.RequestException as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(str(exc)) from exc
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(str(exc)) from exc
    finally:
        if own:
            session.close()

    try:
        size = partial.stat().st_size
        if release.size and size != release.size:
            raise UpdateError(f"expected {release.size} bytes, got {size}")
        if size < MIN_PLAUSIBLE_BYTES:
            raise UpdateError(f"only {size} bytes, not an executable")
        with open(partial, "rb") as handle:
            if handle.read(2) != b"MZ":
                raise UpdateError("the downloaded file is not a Windows program")
        # Only now does it take the name the install step looks for, so a failed
        # or interrupted download can never be mistaken for a finished one.
        partial.replace(destination)
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(str(exc)) from exc

    log.info("downloaded %s (%.1f MB)", destination,
             destination.stat().st_size / (1024 * 1024))
    return destination


def install(staged: Path, target: Path) -> Path:
    """Put ``staged`` in ``target``'s place. Returns the backup's path.

    The running program is the file being replaced, so this is the rename dance
    described at the top of the module. Ordered so that no failure leaves the
    user without an executable: the old one is only moved aside once the new one
    is on disk and verified, and if the second rename fails the first is undone.
    """
    if not staged.exists():
        raise UpdateError(f"{staged.name} is missing")

    backup = backup_path(target)
    try:
        # A leftover from an earlier update would block the rename below.
        backup.unlink(missing_ok=True)
    except OSError as exc:
        # Still held open by something -- an antivirus reading it, most likely.
        # Go around it rather than refuse the update; cleanup() globs for these.
        log.info("could not remove %s (%s)", backup.name, exc)
        for index in range(1, 100):
            candidate = target.with_name(f"{target.stem}.previous-{index}.exe")
            if not candidate.exists():
                backup = candidate
                break
        else:
            raise UpdateError("too many leftover copies of the previous version")

    try:
        target.rename(backup)
    except OSError as exc:
        raise UpdateError(f"could not move the current version aside ({exc})") from exc

    try:
        staged.rename(target)
    except OSError as exc:
        try:
            backup.rename(target)
            log.info("restored %s after a failed swap", target)
        except OSError:
            # Both renames failed, which leaves the old executable under the
            # backup name. Said plainly, because the fix is one rename by hand.
            raise UpdateError(
                f"the update failed and the old version is now named "
                f"{backup.name}; rename it back to {target.name}") from exc
        raise UpdateError(f"could not put the new version in place ({exc})") from exc

    log.info("installed %s, previous version kept as %s", target, backup.name)
    return backup


def cleanup(directory: Path) -> int:
    """Delete what an update left behind. Returns how many files went.

    Called at start-up, which is the first moment the replaced executable is no
    longer running and can therefore be deleted. This is what keeps a folder
    holding one program rather than one per release.
    """
    removed = 0
    for path in directory.glob("Flashwatch.previous*.exe"):
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            log.info("could not remove %s (%s)", path.name, exc)
    for leftover in (STAGED_NAME, STAGED_NAME + ".part"):
        path = directory / leftover
        if not path.exists():
            continue
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            log.info("could not remove %s (%s)", path.name, exc)
    if removed:
        log.info("cleaned up %d file(s) from a previous update", removed)
    return removed


def relaunch(target: Path) -> bool:
    """Start the freshly installed executable, detached from this process.

    Detached matters: the copy being replaced is about to exit, and a child in
    its process group would be asked to exit with it.
    """
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        flags |= getattr(subprocess, name, 0)
    try:
        subprocess.Popen([str(target)], cwd=str(target.parent),
                         creationflags=flags, close_fds=True)
        return True
    except OSError as exc:
        log.warning("could not relaunch %s (%s)", target, exc)
        return False
