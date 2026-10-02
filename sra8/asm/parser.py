"""Lexical rules and operand parsing of the assembly language (spec 3.1-3.4)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .preprocess import AsmError

IDENT = r"[A-Za-z_][A-Za-z0-9_.]*"

RE_IDENT = re.compile(IDENT)
RE_LABEL_DEF = re.compile(r"(\.l\s+)?(" + IDENT + r")\s*:\s*")
RE_REGISTER = re.compile(r"[rR]([0-9]|1[0-5])([aA]?)")
RE_LABEL_REF = re.compile(r"(?:\.([bf])\s+)?=\s*(" + IDENT + r")\s*(?:([+-])\s*(.+))?")
RE_NUMBER = re.compile(r"[+-]?(?:0[bBoOdDxX])?[0-9A-Fa-f]+")

RADIX = {"0b": 2, "0o": 8, "0d": 10, "0x": 16}
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", "'": "'", '"': '"'}


def unescape(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\":
            i += 1
            if i >= len(s) or s[i] not in ESCAPES:
                raise AsmError("bad escape sequence in '%s'" % s)
            out.append(ESCAPES[s[i]])
        else:
            out.append(s[i])
        i += 1
    return "".join(out)


def parse_number(text: str) -> int:
    """'123', '-0x1f', "'a'" -> int.  Anything else is an error."""
    text = text.strip()
    if len(text) >= 3 and text[0] == "'" and text[-1] == "'":
        ch = unescape(text[1:-1])
        if len(ch) != 1:
            raise AsmError("bad character constant %s" % text)
        return ord(ch)
    if not RE_NUMBER.fullmatch(text):
        if any(op in text[1:] for op in "+-*/()&|<>"):
            raise AsmError("expressions are not supported: '%s'" % text)
        raise AsmError("bad number '%s'" % text)
    sign = 1
    body = text
    if body[0] in "+-":
        sign = -1 if body[0] == "-" else 1
        body = body[1:]
    prefix = body[:2].lower()
    base = RADIX.get(prefix, 10)
    if prefix in RADIX:
        body = body[2:]
    try:
        return sign * int(body, base)
    except ValueError:
        raise AsmError("bad number '%s'" % text)


@dataclass(frozen=True)
class Reg:
    n: int
    pair: bool


@dataclass(frozen=True)
class Imm:
    value: int


@dataclass(frozen=True)
class LabelRef:
    name: str
    direction: str | None       # None, 'b' or 'f'
    offset: int


Operand = "Reg | Imm | LabelRef"


def parse_operand(text: str):
    """One instruction operand: rN, rNa, #number, =label [± n], .b/.f =label [± n]."""
    m = RE_REGISTER.fullmatch(text)
    if m:
        return Reg(int(m.group(1)), bool(m.group(2)))
    if text.startswith("#"):
        return Imm(parse_number(text[1:]))
    return parse_label_ref(text)


def parse_label_ref(text: str) -> LabelRef:
    m = RE_LABEL_REF.fullmatch(text)
    if not m:
        if text.startswith("="):
            raise AsmError("bad label reference '%s' (only =label, =label + n, =label - n)" % text)
        raise AsmError("bad operand '%s'" % text)
    offset = 0
    if m.group(3):
        offset = parse_number(m.group(4))
        if m.group(3) == "-":
            offset = -offset
        if not -0x8000 <= offset <= 0xFFFF:
            raise AsmError("offset %d out of range" % offset)
    return LabelRef(m.group(2), m.group(1), offset)


def parse_value(text: str):
    """A directive argument: '#' is optional for numbers."""
    if text[:1] in "=.":
        return parse_label_ref(text)
    return Imm(parse_number(text[1:] if text.startswith("#") else text))


def split_operands(text: str) -> list[str]:
    parts: list[str] = []
    cur = []
    quote = None
    escaped = False
    for ch in text:
        if escaped:
            cur.append(ch)
            escaped = False
        elif quote:
            cur.append(ch)
            if ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch == ",":
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if quote:
        raise AsmError("unterminated string")
    rest = "".join(cur).strip()
    if rest or parts:
        parts.append(rest)
    if "" in parts:
        raise AsmError("empty operand")
    return parts
