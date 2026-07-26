# -*- coding: utf-8 -*-
"""Keeping the user's configuration across an update.

Two ways a copy gets updated, and the settings have to survive both:

* **from inside the program** -- the .exe is renamed over itself in the same
  directory, and ``assets/settings.json`` sits beside it untouched. Nothing here
  tests that, because there is nothing to test: ``test_updater.py`` proves the
  swap only ever touches .exe files;
* **by hand** -- the .exe is downloaded from the releases page and run from
  wherever the browser dropped it. That is a *new* data root with no settings in
  it, and without the breadcrumb below a configured copy comes up blank.

Plus the case that only shows up later: a settings file written by a version that
knows keys this one does not. It must come back out with those keys intact rather
than silently stripped.

Everything runs against temporary directories; no real configuration is read or
written.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import _bootstrap  # noqa: F401,E402 -- puts src/ on the import path

import settings as settings_module                    # noqa: E402
from settings import Settings                         # noqa: E402

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


work = Path(tempfile.mkdtemp(prefix="flashwatch-config-"))


def install_dir(name):
    """A pretend install: a folder with an ``assets`` directory inside it."""
    root = work / name
    (root / "assets").mkdir(parents=True, exist_ok=True)
    return root


def config_of(root):
    return root / "assets" / "settings.json"


def write_config(root, values):
    config_of(root).write_text(json.dumps(values), "utf-8")


# ------------------------------------------------- a manually updated copy
old = install_dir("old-version")
new = install_dir("downloads")
breadcrumb = work / "crumbs" / "last-data-root.txt"

# The old copy runs, configures itself, and leaves its note.
write_config(old, {"theme": "neon", "overlay_x": 777, "locale": "en_US"})
settings_module.remember_data_root(old, breadcrumb)
check("a run records where its data lives", breadcrumb.exists())

# The user downloads the new .exe somewhere else entirely and double-clicks it.
adopted = settings_module.carry_config_forward(config_of(new), breadcrumb, new)
check("a copy started in a new folder adopts the previous settings", adopted)
check("  and reads the values the user had set",
      Settings(config_of(new)).get("overlay_x") == 777)
check("  including the language, which decides the whole interface",
      Settings(config_of(new)).get("locale") == "en_US")
check("  without touching the old install",
      json.loads(config_of(old).read_text("utf-8"))["theme"] == "neon")
check("  and the note now points at the new folder",
      breadcrumb.read_text("utf-8").strip() == str(new))

# Second start-up of that same copy: there is nothing left to carry, and above
# all nothing to overwrite -- by now these are the settings being used.
Settings(config_of(new)).set("overlay_x", 12)
again = settings_module.carry_config_forward(config_of(new), breadcrumb, new)
check("a copy that already has settings adopts nothing", not again)
check("  and keeps its own", Settings(config_of(new)).get("overlay_x") == 12)


# ------------------------------------------------------------ not adopted
fresh = install_dir("fresh")
check("no note at all means a normal first run",
      not settings_module.carry_config_forward(
          config_of(fresh), work / "crumbs" / "absent.txt", fresh))
check("  and nothing is invented", not config_of(fresh).exists())

# The previous install was deleted after updating, which is the tidy thing to do.
gone = install_dir("deleted-later")
crumb_gone = work / "crumbs" / "gone.txt"
settings_module.remember_data_root(gone, crumb_gone)
shutil.rmtree(gone, ignore_errors=True)
target = install_dir("after-cleanup")
check("a note pointing at a deleted install is ignored",
      not settings_module.carry_config_forward(config_of(target), crumb_gone,
                                               target))

# A half-written or hand-mangled file must not be carried into the new copy as
# well; the new one is better off with defaults it can actually load.
broken = install_dir("broken")
config_of(broken).write_text("{not json at all", "utf-8")
crumb_broken = work / "crumbs" / "broken.txt"
settings_module.remember_data_root(broken, crumb_broken)
receiver = install_dir("receiver")
check("unreadable settings are not carried forward",
      not settings_module.carry_config_forward(config_of(receiver),
                                               crumb_broken, receiver))

# The note pointing at the folder we are already in -- every ordinary run of an
# updated-in-place copy -- is a no-op rather than a file copying onto itself.
same = install_dir("same-place")
write_config(same, {"overlay_x": 5})
crumb_same = work / "crumbs" / "same.txt"
settings_module.remember_data_root(same, crumb_same)
check("a note pointing at ourselves is not a source",
      settings_module.previous_config(config_of(same), crumb_same) is None)


# --------------------------------------------------- keys from another version
mixed = install_dir("newer-version")
write_config(mixed, {
    "theme": "light",                    # known
    "a_setting_from_the_future": 42,     # not known to this build
})
store = Settings(config_of(mixed))
check("a known key from the file is used", store.get("theme") == "light")
check("an unknown one is not exposed as a setting",
      store.get("a_setting_from_the_future") is None)

store.set("overlay_x", 99)               # forces a save
written = json.loads(config_of(mixed).read_text("utf-8"))
check("  but it is still on disk afterwards",
      written.get("a_setting_from_the_future") == 42)
check("  alongside what this version wrote", written.get("overlay_x") == 99)

store.reset()
check("a deliberate reset clears it too",
      "a_setting_from_the_future" not in
      json.loads(config_of(mixed).read_text("utf-8")))


# ------------------------------------------------------ defaults for new keys
# The other half of an update: a version that *adds* a setting, reading a file
# written before it existed.
older = install_dir("older-file")
write_config(older, {"overlay_x": 300})
store = Settings(config_of(older))
check("a key missing from an older file falls back to its default",
      store.get("audio_warn_seconds") == settings_module.DEFAULTS["audio_warn_seconds"])
check("  and the values that are there are still honoured",
      store.get("overlay_x") == 300)


shutil.rmtree(work, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
