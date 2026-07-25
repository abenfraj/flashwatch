"""Put ``src/`` on the import path, wherever the checkout happens to live.

Every test is a standalone script run as ``python tests/test_x.py``, so the tests
directory is already on ``sys.path`` and importing this module is enough. It
replaces the absolute path each test used to hardcode, which tied the suite to one
machine and made it unrunnable in CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
