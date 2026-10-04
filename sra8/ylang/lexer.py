"""Tokens of Y (docs/y.md 4)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import YError

KEYWORDS = frozenset("""
decl impl var type internal fn returns struct union opaque
if else loop break continue return
eq ne lt le gt ge not and or
shl shr sar rol ror
true false nullptr undefined _
int8 int16 int32 uint8 uint16 uint32 byte char bool addr
""".split())

BUILTINS = frozenset(["@bool", "@sizeof", "@as", "@cast", "@ptr", "@main", "@section", "@reg"])

PUNCT = ["+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
         "{", "}", "(", ")", "[", "]", ",", ";", ":", ".", "=",
         "+", "-", "*", "/", "%", "&", "|", "^", "~"]

ESCAPES = {"n": 10, "t": 9, "r": 13, "0": 0, "\\": 92, "'": 39, '"': 34}

TOKEN = re.compile(r"""
    (?P<blank>[ \t\r\f]+)
  | (?P<number>0[xX][0-9A-Za-z_]+|0[bBoOdD][0-9A-Za-z_]*|[0-9][0-9A-Za-z_]*)
  | (?P<sstring>s"(?:[^"\\]|\\.)*")
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<char>'(?:[^'\\]|\\.)*')
  | (?P<builtin>@[A-Za-z_][A-Za-z0-9_]*)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<punct>""" + "|".join(re.escape(p) for p in PUNCT) + r""")
""", re.VERBOSE)


@dataclass
class Token:
    kind: str           # 'num' 'char' 'str' 'sstr' 'name' 'kw' 'builtin' 'p' 'eof'
    text: str
    value: object
    where: tuple[str, int]

    def __repr__(self) -> str:
        return "%s %r" % (self.kind, self.text)


def parse_number(text: str, where: tuple[str, int]) -> int:
    bases = {"x": 16, "b": 2, "o": 8, "d": 10}
    try:
        if len(text) > 1 and text[0] == "0" and text[1].lower() in bases:
            if len(text) == 2:
                raise ValueError
            value = int(text[2:], bases[text[1].lower()])
        else:
            value = int(text, 10)
    except ValueError:
        raise YError("bad number '%s'" % text, where) from None
    if value >= 1 << 32:
        raise YError("number '%s' does not fit in 32 bits" % text, where)
    return value


def unescape(body: str, where: tuple[str, int]) -> list[int]:
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            if i + 1 >= len(body) or body[i + 1] not in ESCAPES:
                raise YError("bad escape '%s'" % body[i:i + 2], where)
            out.append(ESCAPES[body[i + 1]])
            i += 2
        else:
            out.append(ord(c) & 0xFF)
            i += 1
    return out


def tokenize(lines: list[tuple[str, int, str]]) -> list[Token]:
    toks: list[Token] = []
    last = ("?", 0)
    for path, no, text in lines:
        where = (path, no)
        last = where
        pos = 0
        while pos < len(text):
            m = TOKEN.match(text, pos)
            if not m:
                raise YError("unexpected character '%s'" % text[pos], where)
            kind = m.lastgroup
            s = m.group(0)
            pos = m.end()
            if kind == "blank":
                continue
            if kind == "number":
                toks.append(Token("num", s, parse_number(s, where), where))
            elif kind == "char":
                v = unescape(s[1:-1], where)
                if len(v) != 1:
                    raise YError("a character literal holds exactly one character", where)
                toks.append(Token("char", s, v[0], where))
            elif kind == "string":
                toks.append(Token("str", s, unescape(s[1:-1], where), where))
            elif kind == "sstring":
                toks.append(Token("sstr", s, unescape(s[2:-1], where), where))
            elif kind == "builtin":
                if s not in BUILTINS:
                    raise YError("unknown builtin '%s'" % s, where)
                toks.append(Token("builtin", s, None, where))
            elif kind == "name":
                toks.append(Token("kw" if s in KEYWORDS else "name", s, None, where))
            else:
                toks.append(Token("p", s, None, where))
    toks.append(Token("eof", "end of file", None, last))
    return toks
