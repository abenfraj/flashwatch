"""Detects whether League is running and where its window is.

Observation only: we enumerate top-level windows and read the process list.
Nothing is injected, no handle into the game is opened for reading memory, and
no game file is touched.

Window enumeration is the primary signal because it is far cheaper than walking
the process table, and the in-game window is what we need the geometry of
anyway. The process list is consulted occasionally, only to distinguish "client
open, no game" from "nothing running" for the status display.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import psutil
import win32gui

from i18n import tr

log = logging.getLogger(__name__)

# The in-game renderer window. The launcher/client is a different class.
GAME_WINDOW_CLASS = "RiotWindowClass"
GAME_PROCESS = "league of legends.exe"
CLIENT_PROCESSES = {"leagueclient.exe", "leagueclientux.exe", "riotclientux.exe"}

PROCESS_POLL_INTERVAL = 5.0

# How long the in-game window may go missing before we conclude the game is over.
#
# Window enumeration is not perfectly reliable from outside: alt-tabbing, a
# resolution change, the loading screen, a minimise, or simply an unlucky moment
# during EnumWindows can all fail to find a window that is still there. Ending the
# session on the first miss meant clearing every timer -- and then starting a
# "new" session on the next poll, clearing them again. Timers vanishing mid-game
# was this, far more often than anything in the OCR.
#
# Generous on purpose: the cost of waiting is that a genuinely finished game keeps
# its timers on screen a few seconds longer, which is invisible (the overlay hides
# itself with the window anyway). The cost of not waiting is losing live data.
WINDOW_LOSS_GRACE = 12.0

# Upper bound on the same patience when the process list still shows the game.
# Guards the one case the pid check cannot: a process scan that keeps failing
# would otherwise return a stale pid forever and hold a finished session open.
WINDOW_LOSS_HARD_LIMIT = 300.0


@dataclass(slots=True)
class GameState:
    in_game: bool = False
    client_running: bool = False
    hwnd: int = 0
    # Client area in virtual-screen coordinates: (left, top, width, height).
    window_rect: tuple[int, int, int, int] | None = None
    session_id: str = ""

    @property
    def running(self) -> bool:
        return self.in_game or self.client_running

    def describe(self) -> str:
        if self.in_game and self.window_rect:
            _, _, width, height = self.window_rect
            return tr("game.in_game", width=width, height=height)
        if self.client_running:
            return tr("game.client_only")
        return tr("game.absent")


def _client_rect_on_screen(hwnd: int) -> tuple[int, int, int, int] | None:
    """Client area of ``hwnd`` in screen coordinates.

    The client rect excludes the title bar and borders, so this works the same
    for fullscreen, borderless and windowed without special-casing any of them.
    """
    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        origin_x, origin_y = win32gui.ClientToScreen(hwnd, (left, top))
    except win32gui.error:
        return None
    width, height = right - left, bottom - top
    if width < 640 or height < 480:
        return None
    return (origin_x, origin_y, width, height)


def find_game_window() -> int:
    """Handle of the visible in-game window, or 0."""
    found = 0

    def callback(hwnd: int, _extra) -> bool:
        nonlocal found
        if found:
            return False
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            if win32gui.GetClassName(hwnd) != GAME_WINDOW_CLASS:
                return True
        except win32gui.error:
            return True
        # The client also briefly owns a RiotWindowClass window; require a
        # game-sized client area to tell them apart.
        if _client_rect_on_screen(hwnd) is not None:
            found = hwnd
            return False
        return True

    try:
        win32gui.EnumWindows(callback, None)
    except win32gui.error as exc:
        # EnumWindows propagates a callback returning False as an error.
        log.debug("EnumWindows stopped early (%s)", exc)
    return found


class GameDetector:
    """Polls for League and reports session changes.

    A *session* is one running instance of the in-game process. When the session
    id changes -- game ended, new game started -- every timer must be cleared,
    which is the caller's cue to reset.
    """

    def __init__(self) -> None:
        self.state = GameState()
        self._last_process_poll = 0.0
        self._cached_client_running = False
        self._cached_game_pid = 0
        # Monotonic time the in-game window was last actually found.
        self._window_last_seen = 0.0

    def poll(self) -> tuple[GameState, bool]:
        """Refresh state. Returns ``(state, session_changed)``."""
        previous_session = self.state.session_id
        now = time.monotonic()

        hwnd = find_game_window()
        rect = _client_rect_on_screen(hwnd) if hwnd else None
        in_game = bool(hwnd and rect)

        client_running, game_pid = self._poll_processes(
            force=in_game and not previous_session)

        # Prefer the pid for session identity: it is stable across window moves
        # and resolution changes, whereas hwnd can be recreated mid-game.
        if in_game:
            self._window_last_seen = now
            session_id = f"pid:{game_pid}" if game_pid else f"hwnd:{hwnd}"
        elif previous_session and self._session_may_still_live(now, game_pid):
            # The window is not answering, but the game has not gone anywhere.
            # Keep the session so the caller keeps its timers; in_game stays False
            # so nothing is captured from a window we cannot see.
            session_id = previous_session
        else:
            session_id = ""

        self.state = GameState(
            in_game=in_game,
            client_running=client_running,
            hwnd=hwnd,
            window_rect=rect,
            session_id=session_id,
        )

        changed = session_id != previous_session
        if changed:
            log.info("session changed: %r -> %r (%s)", previous_session,
                     session_id, self.state.describe())
        return self.state, changed

    def _session_may_still_live(self, now: float, game_pid: int) -> bool:
        """Whether a session whose window just disappeared should be kept.

        Two independent reasons to keep it: the game process is still listed, or
        the window has only been missing for a moment. The pid is the stronger
        signal but it is only refreshed every few seconds, so the grace period
        covers the gap between polls.
        """
        missing_for = now - self._window_last_seen
        if missing_for >= WINDOW_LOSS_HARD_LIMIT:
            return False
        if game_pid:
            return True
        return missing_for < WINDOW_LOSS_GRACE

    def _poll_processes(self, *, force: bool = False) -> tuple[bool, int]:
        """Walk the process table, but rarely -- it is the expensive call."""
        now = time.monotonic()
        if not force and now - self._last_process_poll < PROCESS_POLL_INTERVAL:
            return self._cached_client_running, self._cached_game_pid
        self._last_process_poll = now

        client_running = False
        game_pid = 0
        try:
            for process in psutil.process_iter(["name", "pid"]):
                name = (process.info.get("name") or "").lower()
                if name == GAME_PROCESS:
                    game_pid = process.info.get("pid") or 0
                elif name in CLIENT_PROCESSES:
                    client_running = True
        except (psutil.Error, OSError) as exc:
            log.debug("process scan failed (%s)", exc)
            return self._cached_client_running, self._cached_game_pid

        self._cached_client_running = client_running or bool(game_pid)
        self._cached_game_pid = game_pid
        return self._cached_client_running, self._cached_game_pid
