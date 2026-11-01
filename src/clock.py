"""The clock the timers, the overlay and the capture worker read.

In a game it is ``time.monotonic()`` and nothing else, so this module changes
nothing there. It exists for the replay: a recorded game is read at the speed the
computer can manage, not at the speed it was played, so "how long ago was that
Flash" has to be answered in the *video's* seconds. ``use`` swaps the source for
the length of a replay; ``use(None)`` puts the real clock back.

Every duration in the timer path is measured against ``now()``. A call to
``time.monotonic()`` left behind would mix the two clocks and make a replayed
countdown run at the speed of the replay instead of the game -- which is why the
two pacing reads in the worker's thread loop are the only ones that stay on the
real clock: they decide how long the thread sleeps, not how long a spell has left.
"""

from __future__ import annotations

import time
from typing import Callable

_source: Callable[[], float] = time.monotonic


def now() -> float:
    """Seconds on the current clock: monotonic in a game, video time in a replay."""
    return _source()


def use(source: Callable[[], float] | None) -> None:
    """Read time from ``source`` from now on; ``None`` restores the real clock."""
    global _source
    _source = time.monotonic if source is None else source
