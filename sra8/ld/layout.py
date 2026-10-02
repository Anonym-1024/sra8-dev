"""The link itself (spec 5.3): place sections, resolve symbols, relocate."""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import isa
from ..obj import Object, patch
from .script import Script

MAX_ERRORS = 30


class LinkError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass
class Contribution:
    """One object's section, placed."""
    obj: int
    sec: int
    stype: str
    name: str
    addr: int
    size: int
    data: bytearray | None


@dataclass
class LinkedSymbol:
    name: str
    addr: int
    kind: str                   # exported | script
    obj: int | None


@dataclass
class RegionUse:
    name: str
    start: int
    size: int
    used: int


@dataclass
class Result:
    paths: list[str]
    objects: list[Object]
    contributions: list[Contribution]
    symbols: list[LinkedSymbol]
    regions: list[RegionUse]
    image_start: int = 0
    image: bytes = b""
    base: dict[tuple[int, int], int] = field(default_factory=dict)


def _align(addr: int, n: int) -> int:
    return (addr + n - 1) // n * n


class Linker:
    def __init__(self, script: Script, paths: list[str], objects: list[Object]) -> None:
        self.script = script
        self.paths = paths
        self.objects = objects
        self.errors: list[str] = []
        self.base: dict[tuple[int, int], int] = {}
        self.contribs: list[Contribution] = []
        self.globals: dict[str, int] = {}               # exports and script symbols -> address
        self.export_owner: dict[str, int] = {}
        self.regions: list[RegionUse] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)
        if len(self.errors) >= MAX_ERRORS:
            raise LinkError(self.errors + ["too many errors, stopping"])

    # ---- step 1: exports -------------------------------------------------

    def collect_exports(self) -> None:
        for i, o in enumerate(self.objects):
            for s in o.exports:
                if s.name in self.export_owner:
                    self.err("'%s' is exported by both %s and %s"
                             % (s.name, self.paths[self.export_owner[s.name]], self.paths[i]))
                else:
                    self.export_owner[s.name] = i
        names = set()
        for s in self.script.symbols:
            if s.name in names:
                self.err("%s: script symbol '%s' defined twice" % (s.where, s.name))
            names.add(s.name)
        for p in self.script.places:
            for it in p.items:
                if it.kind == "symbol":
                    if it.name in names:
                        self.err("%s: script symbol '%s' defined twice" % (it.where, it.name))
                    names.add(it.name)
        for n in names:
            if n in self.export_owner:
                self.err("script symbol '%s' is also exported by %s" % (n, self.paths[self.export_owner[n]]))

    # ---- step 2: placement -----------------------------------------------

    def groups(self) -> tuple[dict[tuple[str, str], list[tuple[int, int]]], list[tuple[str, str]]]:
        groups: dict[tuple[str, str], list[tuple[int, int]]] = {}
        order: list[tuple[str, str]] = []
        for i, o in enumerate(self.objects):
            for j, s in enumerate(o.sections):
                key = (s.type, s.name)
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append((i, j))
        return groups, order

    def place(self) -> None:
        groups, order = self.groups()
        placed: set[tuple[str, str]] = set()
        for p in self.script.places:
            region = self.script.regions[p.region]
            cur = region.start
            for it in p.items:
                if it.kind == "align":
                    cur = _align(cur, it.value)
                elif it.kind == "symbol":
                    self.globals[it.name] = cur
                else:
                    if it.name == "*":
                        keys = [k for k in order if k[0] == it.stype and k[1] == "" and k not in placed]
                        keys += [k for k in order if k[0] == it.stype and k[1] != "" and k not in placed]
                    else:
                        key = (it.stype, it.name or "")
                        keys = [key] if key in groups and key not in placed else []
                    for key in keys:
                        placed.add(key)
                        cur = self.place_group(key, groups[key], cur, region, it.where)
                if cur > region.end:
                    cur = region.end
            self.regions.append(RegionUse(region.name, region.start, region.size, cur - region.start))
        for key in order:
            if key in placed:
                continue
            for i, j in groups[key]:
                o = self.objects[i]
                s = o.sections[j]
                used = any(e.section == j for e in o.exports) or any(r.target == j for r in o.relocations)
                if s.size or used:
                    self.err("section %s of %s is not placed by the linker script %s"
                             % (s.label, self.paths[i], self.script.path))

    def place_group(self, key: tuple[str, str], members: list[tuple[int, int]], cur: int, region, where: str) -> int:
        for i, j in members:
            s = self.objects[i].sections[j]
            if s.type == "code":
                cur = _align(cur, isa.INSTR_SIZE)
            if cur + s.size > region.end:
                self.err("%s: section %s of %s (%d bytes at 0x%04X) does not fit into region '%s' (ends at 0x%04X)"
                         % (where, s.label, self.paths[i], s.size, cur, region.name, region.end - 1))
                return region.end
            self.base[(i, j)] = cur
            self.contribs.append(Contribution(i, j, s.type, s.name, cur, s.size,
                                              None if s.data is None else bytearray(s.data)))
            cur += s.size
        return cur

    def script_symbols(self) -> None:
        for s in self.script.symbols:
            if s.kind == "number":
                self.globals[s.name] = s.value
            elif s.kind == "start":
                self.globals[s.name] = self.script.regions[s.region].start
            else:
                self.globals[s.name] = self.script.regions[s.region].end - 1

    # ---- steps 3 and 4: resolve and relocate -------------------------------

    def imported(self, name: str) -> int | None:
        """The address of an exported label or a script symbol."""
        if name in self.export_owner:
            owner = self.export_owner[name]
            e = self.objects[owner].export(name)
            return self.base.get((owner, e.section), 0) + e.offset
        return self.globals.get(name)

    def relocate(self) -> None:
        by_key = {(c.obj, c.sec): c for c in self.contribs}
        unresolved: dict[str, list[str]] = {}
        for i, o in enumerate(self.objects):
            for r in o.relocations:
                if r.symbol is not None:
                    value = self.imported(r.symbol)
                    if value is None:
                        users = unresolved.setdefault(r.symbol, [])
                        if self.paths[i] not in users:
                            users.append(self.paths[i])
                        continue
                    value += r.addend
                else:
                    value = self.base.get((i, r.target), 0) + r.index
                c = by_key.get((i, r.section))
                if c is not None and c.data is not None:
                    patch(c.data, r.offset, r.type, value)
        for name, users in unresolved.items():
            self.err("undefined symbol '%s', imported by %s" % (name, ", ".join(users)))

    def check(self) -> None:
        for c in self.contribs:
            if c.stype == "code" and c.addr % isa.INSTR_SIZE:
                self.err("code section of %s at 0x%04X is not 4-aligned" % (self.paths[c.obj], c.addr))

    # ---- result ----------------------------------------------------------

    def symbols(self) -> list[LinkedSymbol]:
        out = []
        for i, o in enumerate(self.objects):
            for e in o.exports:
                if (i, e.section) in self.base:
                    out.append(LinkedSymbol(e.name, self.base[(i, e.section)] + e.offset, "exported", i))
        exported = set(self.export_owner)
        for name, addr in self.globals.items():
            if name not in exported:
                out.append(LinkedSymbol(name, addr, "script", None))
        return out

    def image(self) -> tuple[int, bytes]:
        loaded = [c for c in self.contribs if c.data is not None and c.size]
        if not loaded:
            return 0, b""
        starts = []
        for r in self.script.regions.values():
            if any(r.start <= c.addr < r.end for c in loaded):
                starts.append(r.start)
        start = min(starts)
        end = max(c.addr + c.size for c in loaded)
        img = bytearray(end - start)
        for c in loaded:
            img[c.addr - start:c.addr - start + c.size] = c.data
        return start, bytes(img)

    def link(self) -> Result:
        self.collect_exports()
        self.place()
        self.script_symbols()
        if not self.errors:
            self.relocate()
            self.check()
        if self.errors:
            raise LinkError(self.errors)
        start, img = self.image()
        res = Result(self.paths, self.objects, sorted(self.contribs, key=lambda c: c.addr),
                     self.symbols(), self.regions, start, img, dict(self.base))
        return res


def link(script: Script, paths: list[str], objects: list[Object]) -> Result:
    return Linker(script, paths, objects).link()
