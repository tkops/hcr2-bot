"""Turns the CLI's ❌ status convention into a process exit code.

Every error in this CLI is printed as a line starting with the ❌ prefix from
`modules.common.STATUS_PREFIXES` — 60+ places rely on that. Rather than
threading return values through every handler, `main()` watches stdout for
those lines and exits non-zero, so callers (bot.py, scripts, CI) can check the
exit code instead of grepping output for words like "invalid".

Code that fails without printing an ❌ line can call `mark_failure()`.
"""

from __future__ import annotations

from typing import TextIO


ERROR_PREFIX = "❌"
EXIT_FAILURE = 1

_explicit_failure = False


def mark_failure() -> None:
    global _explicit_failure
    _explicit_failure = True


def failure_marked() -> bool:
    return _explicit_failure


def reset() -> None:
    global _explicit_failure
    _explicit_failure = False


def is_error_line(line: str) -> bool:
    return line.lstrip().startswith(ERROR_PREFIX)


class ErrorSniffingWriter:
    """Pass-through stdout wrapper that remembers whether an ❌ line was written."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._pending = ""
        self.saw_error = False

    def write(self, data: str) -> int:
        self._pending += data
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._inspect(line)
        return self._stream.write(data)

    def flush(self) -> None:
        self._stream.flush()

    def finish(self) -> None:
        """Inspect a trailing line that was never terminated by a newline."""
        if self._pending:
            self._inspect(self._pending)
            self._pending = ""

    def _inspect(self, line: str) -> None:
        if is_error_line(line):
            self.saw_error = True

    def __getattr__(self, name: str):
        return getattr(self._stream, name)
