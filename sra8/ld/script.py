"""Linker script language (spec 5.2).

A line-oriented language with three statements::

    memory NAME start ADDR size BYTES
    place REGION
        code|data|bss [NAME | *]
        align N
        symbol NAME
    end
    symbol NAME = NUMBER | start REGION | last REGION

``;`` starts a comment.  Numbers are decimal, ``0x…`` or ``0b…``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SECTION_TYPES = ("code", "data", "bss")
KEYWORDS = ("memory", "start", "size", "place", "end", "align", "symbol", "last") + SECTION_TYPES
RE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")


class ScriptError(Exception):
    pass


@dataclass
class Region:
    name: str
    start: int
    size: int
    where: str

    @property
    def end(self) -> int:
        """One past the last address."""
        return self.start + self.size


@dataclass
class PlaceItem:
    kind: str                   # section | align | symbol
    where: str
    stype: str = ""             # section: code / data / bss
    name: str | None = None     # section: None = unnamed, "*" = all remaining; symbol: its name
    value: int = 0              # align: N


@dataclass
class Place:
    region: str
    where: str
    items: list[PlaceItem] = field(default_factory=list)


@dataclass
class ScriptSymbol:
    name: str
    kind: str                   # number | start | last
    where: str
    value: int = 0
    region: str = ""


@dataclass
class Script:
    path: str
    regions: dict[str, Region] = field(default_factory=dict)
    places: list[Place] = field(default_factory=list)
    symbols: list[ScriptSymbol] = field(default_factory=list)


def parse_number(text: str, where: str) -> int:
    t = text.lower()
    try:
        if re.fullmatch(r"0x[0-9a-f]+", t):
            return int(t[2:], 16)
        if re.fullmatch(r"0b[01]+", t):
            return int(t[2:], 2)
        if re.fullmatch(r"[0-9]+", t):
            return int(t, 10)
    except ValueError:
        pass
    raise ScriptError("%s: bad number '%s'" % (where, text))


def _name(text: str, where: str, what: str) -> str:
    if not RE_NAME.fullmatch(text) or text in KEYWORDS:
        raise ScriptError("%s: bad %s name '%s'" % (where, what, text))
    return text


def parse(text: str, path: str = "<script>") -> Script:
    script = Script(path)
    place: Place | None = None
    for line_no, raw in enumerate(text.split("\n"), 1):
        where = "%s:%d" % (path, line_no)
        words = raw.split(";", 1)[0].split()
        if not words:
            continue
        kw = words[0]
        if place is not None:
            if kw == "end":
                if len(words) != 1:
                    raise ScriptError("%s: 'end' takes nothing" % where)
                script.places.append(place)
                place = None
            elif kw in SECTION_TYPES:
                if len(words) > 2:
                    raise ScriptError("%s: expected  %s [NAME | *]" % (where, kw))
                name = None
                if len(words) == 2:
                    name = words[1] if words[1] == "*" else _name(words[1], where, "section")
                place.items.append(PlaceItem("section", where, kw, name))
            elif kw == "align":
                if len(words) != 2:
                    raise ScriptError("%s: expected  align N" % where)
                n = parse_number(words[1], where)
                if n < 1:
                    raise ScriptError("%s: align needs a positive number" % where)
                place.items.append(PlaceItem("align", where, value=n))
            elif kw == "symbol":
                if len(words) != 2:
                    raise ScriptError("%s: inside 'place' a symbol takes the current address: symbol NAME" % where)
                place.items.append(PlaceItem("symbol", where, name=_name(words[1], where, "symbol")))
            else:
                raise ScriptError("%s: '%s' is not allowed inside 'place' (code, data, bss, align, symbol, end)" % (where, kw))
            continue

        if kw == "memory":
            if len(words) != 6 or words[2] != "start" or words[4] != "size":
                raise ScriptError("%s: expected  memory NAME start ADDR size BYTES" % where)
            name = _name(words[1], where, "region")
            if name in script.regions:
                raise ScriptError("%s: region '%s' already declared" % (where, name))
            r = Region(name, parse_number(words[3], where), parse_number(words[5], where), where)
            if r.size < 1 or r.end > 0x10000:
                raise ScriptError("%s: region '%s' must lie within 0x0000 .. 0xFFFF" % (where, name))
            for other in script.regions.values():
                if r.start < other.end and other.start < r.end:
                    raise ScriptError("%s: region '%s' overlaps '%s'" % (where, name, other.name))
            script.regions[name] = r
        elif kw == "place":
            if len(words) != 2:
                raise ScriptError("%s: expected  place REGION" % where)
            if words[1] not in script.regions:
                raise ScriptError("%s: unknown region '%s'" % (where, words[1]))
            if any(p.region == words[1] for p in script.places):
                raise ScriptError("%s: region '%s' already has a place block" % (where, words[1]))
            place = Place(words[1], where)
        elif kw == "symbol":
            if len(words) == 4 and words[2] == "=":
                sym = ScriptSymbol(_name(words[1], where, "symbol"), "number", where,
                                   value=parse_number(words[3], where))
                if not 0 <= sym.value <= 0xFFFF:
                    raise ScriptError("%s: value out of range" % where)
            elif len(words) == 5 and words[2] == "=" and words[3] in ("start", "last"):
                if words[4] not in script.regions:
                    raise ScriptError("%s: unknown region '%s'" % (where, words[4]))
                sym = ScriptSymbol(_name(words[1], where, "symbol"), words[3], where, region=words[4])
            else:
                raise ScriptError("%s: expected  symbol NAME = NUMBER | start REGION | last REGION" % where)
            script.symbols.append(sym)
        elif kw in SECTION_TYPES or kw in ("align", "end"):
            raise ScriptError("%s: '%s' is only allowed inside a 'place' block" % (where, kw))
        else:
            raise ScriptError("%s: unknown statement '%s' (memory, place, symbol)" % (where, kw))
    if place is not None:
        raise ScriptError("%s: 'place' block is not closed with 'end'" % place.where)
    return script


def load(path: str) -> Script:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return parse(f.read(), path)
    except OSError as e:
        raise ScriptError("cannot read '%s': %s" % (path, e.strerror))
