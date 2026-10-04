"""The line-based preprocessor of Y (docs/y.md 3).

Comments are removed first (newlines are kept, so line numbers stay
right), then directives are executed and ``!NAME`` aliases expanded.
The result is a list of (file, line, text) for the lexer.
"""

from __future__ import annotations

import os
import re

from .errors import YError

MAX_DEPTH = 32
DIRECTIVE = re.compile(r"^\s*!(INCLUDE|DEFINE|IFDEF|IFNDEF|ELSE|ENDIF)(?![A-Za-z0-9_])\s*(.*?)\s*$")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")

Line = tuple[str, int, str]


def strip_comments(text: str, path: str) -> str:
    """Replace comments by blanks, keeping newlines and literals."""
    out = []
    i, n, line = 0, len(text), 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            out.append(c)
            i += 1
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n) if j < n and text[j] == c else j
            out.append(text[i:j])
            i = j
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise YError("unterminated comment", (path, line))
            body = text[i:end + 2]
            out.append("".join("\n" if ch == "\n" else " " for ch in body))
            line += body.count("\n")
            i = end + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


class Preprocessor:
    def __init__(self, include_dirs: list[str] | None = None, defines: dict[str, str] | None = None) -> None:
        self.include_dirs = include_dirs or []
        self.defines: dict[str, str] = dict(defines or {})
        self.out: list[Line] = []

    # -- alias expansion ---------------------------------------------------------

    def expand(self, text: str, where: tuple[str, int], stack: tuple[str, ...] = ()) -> str:
        res = []
        i, n = 0, len(text)
        while i < n:
            c = text[i]
            if c in "\"'":
                j = i + 1
                while j < n and text[j] != c:
                    j += 2 if text[j] == "\\" else 1
                res.append(text[i:j + 1])
                i = j + 1
            elif c == "!":
                m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", text[i + 1:])
                if not m:
                    res.append(c)
                    i += 1
                    continue
                name = m.group(0)
                if name not in self.defines:
                    raise YError("undefined alias '!%s'" % name, where)
                if name in stack:
                    raise YError("alias '!%s' refers to itself" % name, where)
                res.append(self.expand(self.defines[name], where, stack + (name,)))
                i += 1 + len(name)
            else:
                res.append(c)
                i += 1
        return "".join(res)

    # -- files ------------------------------------------------------------------

    def find(self, name: str, base: str, where: tuple[str, int]) -> str:
        for d in [os.path.dirname(base)] + self.include_dirs:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
        raise YError("cannot find '%s' to include" % name, where)

    def run_file(self, path: str, depth: int = 0, where: tuple[str, int] | None = None) -> None:
        if depth > MAX_DEPTH:
            raise YError("!INCLUDE nested too deep", where)
        try:
            with open(path, "r", encoding="latin-1") as f:
                text = f.read()
        except OSError as e:
            raise YError("cannot read '%s': %s" % (path, e.strerror), where) from None
        lines = strip_comments(text, path).split("\n")
        # conditional stack: [keeping, taken, saw_else]
        stack: list[list[bool]] = []

        def keeping() -> bool:
            return all(s[0] for s in stack)

        for no, raw in enumerate(lines, 1):
            here = (path, no)
            m = DIRECTIVE.match(raw)
            if not m:
                if keeping() and raw.strip():
                    self.out.append((path, no, self.expand(raw, here)))
                continue
            d, rest = m.group(1), m.group(2)
            if d in ("IFDEF", "IFNDEF"):
                name = self.name_of(rest, d, here)
                outer = keeping()
                hit = (name in self.defines) == (d == "IFDEF")
                stack.append([outer and hit, outer and hit, False])
            elif d == "ELSE":
                if not stack or stack[-1][2]:
                    raise YError("!ELSE without !IFDEF or !IFNDEF", here)
                top = stack[-1]
                outer = all(s[0] for s in stack[:-1])
                if rest:
                    sub = rest.split(None, 1)
                    if sub[0] not in ("IFDEF", "IFNDEF") or len(sub) != 2:
                        raise YError("expected '!ELSE', '!ELSE IFDEF NAME' or '!ELSE IFNDEF NAME'", here)
                    name = self.name_of(sub[1], sub[0], here)
                    hit = (name in self.defines) == (sub[0] == "IFDEF")
                    top[0] = outer and not top[1] and hit
                    top[1] = top[1] or top[0]
                else:
                    top[0] = outer and not top[1]
                    top[1] = True
                    top[2] = True
            elif d == "ENDIF":
                if not stack:
                    raise YError("!ENDIF without !IFDEF or !IFNDEF", here)
                if rest:
                    raise YError("unexpected text after !ENDIF", here)
                stack.pop()
            elif not keeping():
                continue
            elif d == "DEFINE":
                parts = rest.split(None, 1)
                if not parts or not NAME.match(parts[0]):
                    raise YError("expected '!DEFINE NAME text'", here)
                if parts[0] in self.defines:
                    raise YError("alias '!%s' is already defined" % parts[0], here)
                self.defines[parts[0]] = parts[1] if len(parts) > 1 else ""
            elif d == "INCLUDE":
                name = self.expand(rest, here).strip()
                if not name:
                    raise YError("expected '!INCLUDE path'", here)
                self.run_file(self.find(name, path, here), depth + 1, here)
        if stack:
            raise YError("missing !ENDIF", (path, len(lines)))

    @staticmethod
    def name_of(text: str, directive: str, where: tuple[str, int]) -> str:
        if not NAME.match(text):
            raise YError("expected '!%s NAME'" % directive, where)
        return text


def preprocess(path: str, include_dirs: list[str] | None = None,
               defines: dict[str, str] | None = None) -> list[Line]:
    pp = Preprocessor(include_dirs, defines)
    pp.run_file(path)
    return pp.out
