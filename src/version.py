"""The application's version.

A single line, rewritten by the release workflow just before it packages the
executable, so a built copy always knows which release it is. Running from source
it stays at the placeholder -- which is the honest answer: a working copy is not
any released version.

Kept in its own module so stamping it cannot disturb anything else, and so the
value is importable without pulling in Qt.
"""

__version__ = "0.0.0-dev"
