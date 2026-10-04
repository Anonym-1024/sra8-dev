"""The one exception of the compiler: a message with a source position."""

from __future__ import annotations

Where = tuple[str, int]          # (file, line)


class YError(Exception):
    def __init__(self, msg: str, where: Where | None = None) -> None:
        super().__init__(msg)
        self.msg = msg
        self.where = where

    def __str__(self) -> str:
        if self.where:
            return "%s:%d: error: %s" % (self.where[0], self.where[1], self.msg)
        return "error: %s" % self.msg
