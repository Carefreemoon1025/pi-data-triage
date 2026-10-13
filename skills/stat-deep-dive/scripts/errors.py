"""Error envelope shared by the stat-deep-dive entry point."""

from __future__ import annotations

EXIT_USAGE = 2
EXIT_LOAD = 3
EXIT_MISMATCH = 4
EXIT_DEPENDENCY = 5
EXIT_UNEXPECTED = 1


class StatError(Exception):
    """A failure that already knows its machine code, hint and exit code."""

    def __init__(self, code: str, message: str, hint: str, exit_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = exit_code
