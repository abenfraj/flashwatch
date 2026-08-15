# -*- coding: utf-8 -*-
"""One copy at a time, and a second launch that opens the first one's window.

Two copies of Flashwatch is not a tidiness problem: both would OCR the same chat
at 200 ms, both would draw an overlay, and the two would sit on top of each other
showing slightly different times. And a second launch is the easy mistake --
packaged as a single .exe there is no window and no cursor feedback for the first
few seconds, so double-clicking again is the obvious thing to do.

Two things are needed, and they are two different mechanisms:

**The token.** A *named mutex* says "somebody is running" across the whole login
session, whatever folder each copy was started from, and the kernel drops it when
the process dies however it dies -- which a lock file alone could not promise. Its
one weakness is that it needs pywin32: the old code, unable to check, let the copy
run, and that is exactly how two instances ended up live at once (one started by
the project's venv, one by a system Python without pywin32). So a *byte-range lock
on a file* is taken as well, with nothing but the standard library, and either one
being held is enough to stand down. Both are taken by every copy, so a copy that
can only see one of them still collides with a copy holding both.

**The knock.** Standing down silently is worse than useless -- the whole reason
the user launched again is that they could not find the window, which lives in the
notification area with no taskbar button (``ui.py``'s window is a ``Qt.Tool``). So
the refused copy writes a file next to the lock and waits; the running copy polls
for it, deletes it, and shows its window. Deleting it is the acknowledgement: if
it is still there after a moment, nobody is listening -- the token is held by
something wedged -- and *then* the refused copy says so in a message box, which is
the only case where it is worth interrupting anybody.

Not a socket, and not a Qt mechanism. ``QLocalServer`` would be the idiomatic
answer, but QtNetwork is one of the module families ``build.py`` drops from the
bundle, and a listening socket in a program that watches a game is the sort of
thing a firewall asks about. A file in ``%LOCALAPPDATA%`` asks nobody anything.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

try:                                                  # Windows only, by design.
    import msvcrt
except ImportError:                                   # pragma: no cover
    msvcrt = None                                     # type: ignore[assignment]

# The default token name. Anything else is a test wanting its own, so that a
# suite can exercise this while the real application is running on the machine.
NAME = "Flashwatch.instance"

# Beside the breadcrumb in ``settings.py`` rather than in the data root, and for
# the same reason the mutex is not per-folder: two installs in two directories are
# still two overlays. This is the one place both of them can agree on.
STATE_DIR = (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Flashwatch")

# How long a refused copy waits for the running one to answer its knock. The
# poll below runs at 800 ms, and the answer costs a file delete.
ANSWER_TIMEOUT = 3.0
POLL_MS = 800


def _paths(name: str) -> tuple[Path, Path]:
    """The lock and the knock for a token name."""
    stem = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in name)
    return STATE_DIR / f"{stem}.lock", STATE_DIR / f"{stem}.knock"


class Token:
    """What the one running copy holds, and gives back on the way out.

    Kept as an object rather than as a handle so that releasing it is one call
    whatever it is made of -- the updater has to let go early, and it should not
    have to know whether this machine had pywin32.
    """

    __slots__ = ("name", "_mutex", "_fd")

    def __init__(self, name: str, mutex=None, fd: int | None = None) -> None:
        self.name = name
        self._mutex = mutex
        self._fd = fd

    def release(self) -> None:
        """Give up the token. Idempotent: called on exit and before an update."""
        if self._fd is not None:
            fd, self._fd = self._fd, None
            try:
                if msvcrt is not None:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError as exc:                    # pragma: no cover
                log.debug("could not unlock the instance file (%s)", exc)
            try:
                os.close(fd)
            except OSError:                           # pragma: no cover
                pass
        if self._mutex is not None:
            mutex, self._mutex = self._mutex, None
            try:
                import win32api
                win32api.CloseHandle(mutex)
            except Exception as exc:                  # noqa: BLE001
                log.debug("could not release the instance mutex (%s)", exc)
        log.info("single-instance token released")


def _claim_mutex(name: str):
    """The session-wide half. Returns the handle, or False if it is taken."""
    try:
        import win32api
        import win32event
        import winerror
    except ImportError:                               # pragma: no cover
        return None                                   # cannot check; the file can
    handle = win32event.CreateMutex(None, False, name)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        # A handle comes back even when the mutex already existed; closing it
        # keeps the refused copy from holding a reference to the token.
        if handle:
            win32api.CloseHandle(handle)
        return False
    return handle


def _claim_file(path: Path):
    """The half that needs nothing installed. Returns the fd, or False.

    A byte-range lock rather than the file's existence: Windows ties the lock to
    the handle and drops it when the process ends, crash included, so this cannot
    leave a machine locked out the way a stale marker file would.
    """
    if msvcrt is None:                                # pragma: no cover
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT)
    except OSError as exc:                            # pragma: no cover
        log.debug("could not open %s (%s)", path, exc)
        return None                                   # cannot check; the mutex can
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError:
        os.close(fd)
        return False
    return fd


def acquire(name: str = NAME) -> Token | None:
    """Claim the "only one running" token, or return None if it is taken.

    Both halves are claimed, and either one refusing is a refusal: a copy that
    can only check one of them must still stand down for a copy holding the
    other.
    """
    lock_path, knock_path = _paths(name)
    mutex = _claim_mutex(name)
    if mutex is False:
        return None
    fd = _claim_file(lock_path)
    if fd is False:
        if mutex:
            Token(name, mutex=mutex).release()
        return None
    # A knock left behind by a copy that gave up while nobody was listening would
    # otherwise pop this one's window open seconds after it started.
    _forget_knock(knock_path)
    return Token(name, mutex=mutex or None, fd=fd if fd is not None else None)


def _forget_knock(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def knock(name: str = NAME, timeout: float = ANSWER_TIMEOUT) -> bool:
    """Ask the running copy to show its window. True if it answered.

    An answer is the knock file being deleted, which is the running copy saying
    "I have it" rather than a promise made by whoever wrote the file.
    """
    _, path = _paths(name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(os.getpid()), "utf-8")
    except OSError as exc:
        log.debug("could not knock at %s (%s)", path, exc)
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not path.exists():
            log.info("the running copy answered the knock")
            return True
        time.sleep(0.1)
    log.warning("nobody answered the knock at %s", path)
    _forget_knock(path)
    return False


def take_knock(name: str = NAME) -> bool:
    """Owner side: has another copy asked us to show ourselves?

    Consuming the knock *is* the acknowledgement, so the file is removed before
    this returns True -- and if it cannot be removed, this returns False rather
    than raising the window on every tick from then on.
    """
    _, path = _paths(name)
    try:
        if not path.exists():
            return False
        path.unlink()
    except OSError as exc:
        log.debug("could not take the knock at %s (%s)", path, exc)
        return False
    log.info("another copy was launched; showing the window")
    return True
