# -*- coding: utf-8 -*-
"""The in-app updater: version arithmetic, the download guards, and the swap.

The swap is the part worth testing hardest. It replaces the executable the user
runs, and it does so while that executable is running, so every failure mode has
to leave a working program behind:

* a download that arrives truncated, or as a proxy's sign-in page, must never be
  renamed over anything;
* the old version is only moved aside once the new one is on disk and verified;
* if putting the new one in place fails anyway, the old one comes back.

Everything here runs against a temporary directory and a fake HTTP session, so no
network and no real executable are involved.
"""
import io
import shutil
import sys
import tempfile
from pathlib import Path

import _bootstrap  # noqa: F401,E402 -- puts src/ on the import path

import updater                                        # noqa: E402

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' -- ' + extra) if extra else ''}")


# --------------------------------------------------------------- versions
check("a plain version parses", updater.parse_version("1.2.3") == (1, 2, 3))
check("a tag parses the same way", updater.parse_version("v1.2.3") == (1, 2, 3))
check("the dev placeholder parses as zero",
      updater.parse_version("0.0.0-dev") == (0, 0, 0))
check("junk parses as nothing", updater.parse_version("nightly") is None)

check("a later patch is newer", updater.is_newer("0.1.4", "0.1.3"))
check("the same version is not newer", not updater.is_newer("0.1.3", "0.1.3"))
check("an older version is not newer", not updater.is_newer("0.1.2", "0.1.3"))
# Compared as numbers, not as text: "0.1.10" sorts before "0.1.9" as a string,
# and a release that never offers itself is the kind of bug nobody reports.
check("10 is newer than 9, not older", updater.is_newer("0.1.10", "0.1.9"))
check("a tag compares against a stamped version",
      updater.is_newer("v0.2.0", "0.1.9"))
check("unparseable means no", not updater.is_newer("", "0.1.3"))


# ------------------------------------------------------------ fake HTTP
class FakeResponse:
    def __init__(self, payload=None, body=b"", status=200, headers=None):
        self._payload = payload
        self._body = body
        self.status = status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status}")

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    def iter_content(self, size):
        stream = io.BytesIO(self._body)
        while True:
            chunk = stream.read(size)
            if not chunk:
                return
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class FakeSession:
    """Answers whatever the test set up, and records what was asked for."""

    def __init__(self, response):
        self.response = response
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.response

    def close(self):
        pass


def release_payload(tag="v0.2.0", *, asset_name=updater.ASSET_NAME, size=99,
                    draft=False):
    return {
        "tag_name": tag,
        "draft": draft,
        "body": "## Nouveautes\n- quelque chose",
        "html_url": f"https://example.invalid/{tag}",
        "assets": [{"name": asset_name, "size": size,
                    "browser_download_url": f"https://example.invalid/{tag}/exe"}],
    }


# ------------------------------------------------------------ the check
session = FakeSession(FakeResponse(payload=release_payload()))
found = updater.check("0.1.9", session=session)
check("a newer release is offered", found is not None and found.version == "0.2.0",
      found.version if found else "nothing")
check("  its notes come along", found is not None and "Nouveautes" in found.notes)
check("  and the asset url", found is not None and found.download_url.endswith("/exe"))

session = FakeSession(FakeResponse(payload=release_payload("v0.1.9")))
check("the version already installed is not offered",
      updater.check("0.1.9", session=session) is None)

session = FakeSession(FakeResponse(payload=release_payload(asset_name="notes.txt")))
check("a release with no executable attached is not offered",
      updater.check("0.1.0", session=session) is None)

session = FakeSession(FakeResponse(payload=release_payload(draft=True)))
check("a draft is not offered", updater.check("0.1.0", session=session) is None)

session = FakeSession(FakeResponse(status=503))
check("a failed request is not an update", updater.check("0.1.0", session=session) is None)

# fetch_latest keeps "nothing newer" and "could not ask" apart, which is what the
# on-demand check in the settings needs to word its answer.
session = FakeSession(FakeResponse(payload=release_payload("v0.1.9")))
latest = updater.fetch_latest(session=session)
check("fetch_latest returns the current release rather than None",
      latest is not None and latest.version == "0.1.9",
      latest.version if latest else "None")
session = FakeSession(FakeResponse(status=503))
check("fetch_latest returns None only when the lookup failed",
      updater.fetch_latest(session=session) is None)


# --------------------------------------------------------- the download
work = Path(tempfile.mkdtemp(prefix="flashwatch-updater-"))
# The real floor is 40 MB, which is about the smallest a bundle carrying Qt and
# the OCR models could be. Lowered here so the fixtures stay bytes.
updater.MIN_PLAUSIBLE_BYTES = 8

GOOD = b"MZ" + b"\x00" * 30


def fake_release(body, *, size=None):
    return updater.Release(version="0.2.0", tag="v0.2.0", notes="",
                           download_url="https://example.invalid/exe",
                           size=len(body) if size is None else size,
                           page_url="https://example.invalid")


destination = work / updater.STAGED_NAME
session = FakeSession(FakeResponse(body=GOOD))
seen = []
updater.download(fake_release(GOOD), destination,
                 progress=lambda done, total: seen.append((done, total)),
                 session=session)
check("a good download lands", destination.exists()
      and destination.read_bytes() == GOOD)
check("  progress was reported", bool(seen), str(seen[:2]))
check("  and nothing partial is left behind",
      not (work / (updater.STAGED_NAME + ".part")).exists())

for name, body, size in (
        ("a truncated download is refused", GOOD, len(GOOD) + 100),
        ("a file that is not a program is refused", b"<html>sign in</html>", None),
        ("a file too small to be a bundle is refused", b"MZ", None)):
    destination.unlink(missing_ok=True)
    session = FakeSession(FakeResponse(body=body))
    try:
        updater.download(fake_release(body, size=size), destination,
                         session=session)
        check(name, False, "it was accepted")
    except updater.UpdateError as exc:
        check(name, True, str(exc)[:48])
    check(f"  nothing is left on disk after: {name[:34]}",
          not destination.exists()
          and not (work / (updater.STAGED_NAME + ".part")).exists())


# ------------------------------------------------------------- the swap
def fresh_install_dir():
    directory = Path(tempfile.mkdtemp(prefix="flashwatch-swap-"))
    target = directory / updater.ASSET_NAME
    target.write_bytes(b"MZ old version")
    staged = updater.staged_path(target)
    staged.write_bytes(b"MZ new version")
    return directory, target, staged


directory, target, staged = fresh_install_dir()
backup = updater.install(staged, target)
check("the new version takes the executable's name",
      target.read_bytes() == b"MZ new version",
      target.read_bytes().decode(errors="replace"))
check("the old one is kept aside, not deleted",
      backup.exists() and backup.read_bytes() == b"MZ old version")
check("and the staged download is gone", not staged.exists())
check("only the two expected files remain",
      sorted(p.name for p in directory.iterdir())
      == sorted([updater.ASSET_NAME, updater.BACKUP_NAME]),
      str(sorted(p.name for p in directory.iterdir())))

# Start-up cleanup is what keeps one release from becoming a pile of them.
removed = updater.cleanup(directory)
check("cleanup removes the previous version", removed == 1 and not backup.exists())
check("  and leaves the program itself alone", target.exists())
check("  running it again removes nothing", updater.cleanup(directory) == 0)
shutil.rmtree(directory, ignore_errors=True)

# A leftover backup from an earlier update must not block the next one.
directory, target, staged = fresh_install_dir()
updater.backup_path(target).write_bytes(b"MZ ancient")
updater.install(staged, target)
check("a stale backup does not block the swap",
      target.read_bytes() == b"MZ new version")
shutil.rmtree(directory, ignore_errors=True)

# The failure that matters: the old version has been moved aside and putting the
# new one in place fails. The user must still have a program afterwards.
directory, target, staged = fresh_install_dir()
original_rename = Path.rename
attempts = []


def flaky_rename(self, other):
    attempts.append(Path(self).name)
    if len(attempts) == 2:                 # staged -> Flashwatch.exe
        raise OSError("simulated failure")
    return original_rename(self, other)


Path.rename = flaky_rename
try:
    updater.install(staged, target)
    check("a failed swap raises", False, "it reported success")
except updater.UpdateError as exc:
    check("a failed swap raises", True, str(exc)[:44])
finally:
    Path.rename = original_rename

check("the old version is put back after a failed swap",
      target.exists() and target.read_bytes() == b"MZ old version",
      target.read_bytes().decode(errors="replace") if target.exists() else "missing")
check("  and no backup is left pretending to be one",
      not updater.backup_path(target).exists())

missing = directory / "nothing.exe"
try:
    updater.install(missing, target)
    check("installing a download that is not there raises", False)
except updater.UpdateError:
    check("installing a download that is not there raises", True)
check("  and the program is untouched",
      target.read_bytes() == b"MZ old version")
shutil.rmtree(directory, ignore_errors=True)


# ----------------------------------------------------------- writability
directory = Path(tempfile.mkdtemp(prefix="flashwatch-write-"))
check("a writable folder can be installed into",
      updater.can_install(directory / updater.ASSET_NAME))
check("  and the probe leaves nothing behind",
      list(directory.iterdir()) == [], str(list(directory.iterdir())))
check("a folder that does not exist cannot be installed into",
      not updater.can_install(directory / "nope" / updater.ASSET_NAME))
shutil.rmtree(directory, ignore_errors=True)
shutil.rmtree(work, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
