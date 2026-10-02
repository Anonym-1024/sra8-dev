"""Text preprocessor of the assembler: ``!INCLUDE``, ``!DEFINE`` and ``!alias``.

Unchanged from the legacy assembler (spec 3.7), plus the rule that ``;`` is
the only comment syntax: ``//`` and ``/*`` outside quotes are errors.
"""

from __future__ import annotations

import os
import re

MAX_INCLUDE_DEPTH = 32
MAX_EXPAND_DEPTH = 32

RE_ALIAS = re.compile(r"!([A-Za-z_][A-Za-z0-9_]*)")


class AsmError(Exception):
    """An assembly error.  ``where`` (``file:line``) is filled in by the
    first handler that knows the location."""

    def __init__(self, msg: str, where: str | None = None) -> None:
        super().__init__(msg)
        self.msg = msg
        self.where = where

    def __str__(self) -> str:
        return "%s: %s" % (self.where, self.msg) if self.where else self.msg


def strip_comment(text: str) -> str:
    """Remove a ``;`` comment, respecting quotes.  Reject C comments."""
    quote = None
    escaped = False
    for i, ch in enumerate(text):
        if escaped:
            escaped = False
        elif quote:
            if ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == ";":
            return text[:i]
        elif ch == "/" and text[i + 1:i + 2] in ("/", "*"):
            raise AsmError("'%s' is not a comment here: only ';' starts a comment" % text[i:i + 2])
    return text


def expand_aliases(text: str, defines: dict[str, str]) -> str:
    """Replace every ``!alias`` outside of quotes, repeatedly, so aliases may nest."""
    for _ in range(MAX_EXPAND_DEPTH):
        out = []
        quote = None
        changed = False
        i = 0
        while i < len(text):
            ch = text[i]
            m = RE_ALIAS.match(text, i) if ch == "!" and not quote else None
            if m:
                if m.group(1) not in defines:
                    raise AsmError("undefined alias '!%s'" % m.group(1))
                out.append(defines[m.group(1)])
                changed = True
                i = m.end()
                continue
            if quote:
                if ch == "\\" and i + 1 < len(text):
                    out.append(ch)
                    i += 1
                    ch = text[i]
                elif ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            out.append(ch)
            i += 1
        if not changed:
            return "".join(out)
        text = "".join(out)
    raise AsmError("alias expansion too deep (recursive !DEFINE?)")


def preprocess(path: str, defines: dict[str, str] | None = None,
               out: list[tuple[str, int, str]] | None = None, depth: int = 0) -> list[tuple[str, int, str]]:
    """Read ``path`` and return (file, line number, text) for every non-empty line."""
    if defines is None:
        defines = {}
    if out is None:
        out = []
    if depth > MAX_INCLUDE_DEPTH:
        raise AsmError("!INCLUDE nested too deep", path)
    try:
        with open(path, "r", encoding="latin-1") as f:
            raw_lines = f.read().split("\n")
    except OSError as e:
        raise AsmError("cannot read '%s': %s" % (path, e.strerror))

    for line_no, raw in enumerate(raw_lines, 1):
        where = "%s:%d" % (path, line_no)
        try:
            text = strip_comment(raw.rstrip("\r")).strip()
            if not text:
                continue
            words = text.split(None, 2)
            if words[0] == "!INCLUDE":
                name = expand_aliases(text[len("!INCLUDE"):].strip(), defines)
                if not name:
                    raise AsmError("expected  !INCLUDE file")
                preprocess(os.path.join(os.path.dirname(path), name), defines, out, depth + 1)
            elif words[0] == "!DEFINE":
                if len(words) < 2 or not RE_ALIAS.fullmatch("!" + words[1]):
                    raise AsmError("expected  !DEFINE <alias> <replacement>")
                defines[words[1]] = words[2] if len(words) == 3 else ""
            elif words[0].startswith("!") and words[0][1:].isupper() and words[0][1:] not in defines:
                raise AsmError("unknown preprocessor directive or undefined alias '%s'" % words[0])
            else:
                out.append((path, line_no, expand_aliases(text, defines)))
        except AsmError as e:
            if e.where is None:
                e.where = where
            raise
    return out
