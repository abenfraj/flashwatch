# -*- coding: utf-8 -*-
"""The Windows Run entry: written, read back, and removed.

This one touches the real registry, because a mocked winreg would only prove
that the mock works -- the failure modes here are all real-registry ones
(missing key, missing value, a policy refusing the write).

It is therefore careful to operate under its own value name and to remove it
whatever happens. A test that left "Flashwatch" behind would silently switch on
the very feature it is checking.
"""
import sys, io, os, winreg

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _bootstrap  # noqa: F401,E402 -- puts src/ on the import path

import autostart  # noqa: E402

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


REAL_NAME = autostart.VALUE_NAME
autostart.VALUE_NAME = "FlashwatchSelfTest"

# What the real entry looks like before we start, so we can prove we left it
# alone. None is the normal answer on a machine that never enabled it.
def real_entry():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY) as key:
            return winreg.QueryValueEx(key, REAL_NAME)[0]
    except (FileNotFoundError, OSError):
        return None


before = real_entry()

try:
    check("starts absent", not autostart.is_enabled())
    check("no command when absent", autostart.current_command() is None)

    ok = autostart.set_enabled(True)
    check("enabling reports success", ok)
    check("enabling is visible in the registry", autostart.is_enabled())

    command = autostart.current_command()
    check("the command is quoted", bool(command) and command.startswith('"'),
          repr(command))
    # Whatever it points at -- the frozen exe, or an interpreter plus main.py --
    # the first quoted token has to be a file that exists, or the boot does
    # nothing and says nothing.
    target = command.split('"')[1] if command else ""
    check("the command points at something that exists", os.path.isfile(target),
          target)

    check("enabling twice is idempotent",
          autostart.set_enabled(True) and autostart.current_command() == command)

    # Nothing moved, so there is nothing to rewrite.
    check("refresh_if_moved does nothing when the path is unchanged",
          autostart.refresh_if_moved() is False)

    check("disabling reports success", autostart.set_enabled(False))
    check("disabling removes the entry", not autostart.is_enabled())
    check("disabling twice is harmless", autostart.set_enabled(False))

    # The guard that keeps refresh from being a way in.
    check("refresh_if_moved does not enable a missing entry",
          autostart.refresh_if_moved() is False and not autostart.is_enabled())

finally:
    # Belt and braces: remove the test value even if an assertion above blew up.
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, autostart.VALUE_NAME)
    except (FileNotFoundError, OSError):
        pass
    autostart.VALUE_NAME = REAL_NAME

check("the real Flashwatch entry was left untouched", real_entry() == before,
      f"{before!r} -> {real_entry()!r}")


# ------------------------------------------------- a login is not a launch
# Double-clicking Flashwatch and Windows starting it at login are the same
# process run for opposite reasons: one is somebody asking to see the window, the
# other is the machine getting it ready in the background. The flag on the Run
# entry is the only thing that tells them apart.
check("the boot command carries the flag",
      autostart.STARTUP_FLAG in autostart._command(), autostart._command())
check("a double-click does not",
      not autostart.started_by_windows(["flashwatch.exe"]))
check("a login does",
      autostart.started_by_windows(["flashwatch.exe", autostart.STARTUP_FLAG]))
# An entry written before the flag existed reads as a manual launch, which is the
# harmless way round -- and only until refresh_if_moved rewrites it.
check("an entry from an older build differs, so it gets rewritten",
      '"x.exe"' != autostart._command()
      and not autostart.started_by_windows(['"x.exe"']))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
