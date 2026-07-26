"""Start Flashwatch with Windows, via the per-user Run key.

The point is not the convenience of skipping a double-click: the program has to
already be running when a game begins, because it primes on the first frames of
chat it sees and cannot recover announcements printed before it started.

``HKEY_CURRENT_USER\\...\\Run`` rather than the Startup folder or a scheduled
task. It needs no administrator rights, no shortcut file to write and keep in
step with the executable's location, and Windows already exposes it to the user
under Task Manager's Startup tab -- where they can switch it off without coming
back here, which is the behaviour someone reaches for when a startup entry
annoys them.

That last point drives the design: **the registry is the truth, not a setting**.
Anything stored on our side would go stale the moment the user used Task
Manager, and the checkbox would then lie. :func:`is_enabled` reads the key.
"""

from __future__ import annotations

import logging
import sys
import winreg
from pathlib import Path

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Flashwatch"


def _command() -> str:
    """The command line Windows should run, quoted for the registry.

    Frozen, that is the executable itself. From source it is the interpreter
    plus the entry script -- ``pythonw.exe`` where it exists, so a boot does not
    leave a console window sitting behind everything.
    """
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'

    entry = Path(__file__).resolve().parent / "main.py"
    interpreter = Path(sys.executable).resolve()
    windowless = interpreter.with_name("pythonw.exe")
    if windowless.exists():
        interpreter = windowless
    return f'"{interpreter}" "{entry}"'


def is_enabled() -> bool:
    """Whether the Run entry exists. Read from the registry every time.

    Deliberately not cached and not mirrored into settings.json: the user can
    remove the entry from Task Manager, and a remembered answer would leave the
    checkbox claiming something untrue.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    except OSError as exc:                       # locked-down or unreadable
        log.warning("could not read the autostart key (%s)", exc)
        return False
    return bool(value)


def current_command() -> str | None:
    """What the existing entry runs, or None. Used to spot a stale path."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
    except (FileNotFoundError, OSError):
        return None
    return str(value)


def set_enabled(enabled: bool) -> bool:
    """Add or remove the Run entry. Returns whether the registry now agrees.

    Never raises. A machine can have this key locked down by policy, and a
    checkbox is not worth crashing the program over -- the caller re-reads the
    state and shows what actually happened.
    """
    try:
        if enabled:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
            log.info("autostart enabled: %s", _command())
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
            log.info("autostart disabled")
    except FileNotFoundError:
        # Removing something that is not there is the outcome asked for.
        pass
    except OSError as exc:
        log.warning("could not write the autostart key (%s)", exc)
        return is_enabled() == enabled
    return is_enabled() == enabled


def refresh_if_moved() -> bool:
    """Re-point an existing entry at where the program now lives.

    Flashwatch is portable -- the FAQ tells people to move the folder and keep
    their settings -- so an entry written before a move would silently boot
    nothing. Only ever rewrites an entry that already exists; it must not be a
    back door that switches autostart on.
    """
    existing = current_command()
    if existing is None or existing == _command():
        return False
    log.info("autostart path changed, rewriting (%s -> %s)", existing, _command())
    return set_enabled(True)
