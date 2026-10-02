"""Object files: a JSON text format (spec Section 4, docs/obj.md).

An object holds four things:

* a header: format, version and the source file name
* the sections, each identified by its label: ``code``, ``code:vector``,
  ``data:rodata``, ``bss`` ...
* the exported labels: name, section label, offset
* the relocations

A relocation names the place to patch (section label and offset), how to
patch it (``IMM16``: the immediate of an instruction, big-endian;
``ABS16``: two data bytes, little-endian), and where the address comes
from: either ``from`` a section of this object at ``index``, or an
``import``ed name, looked up among the exports of all objects, plus an
``addend``.  Labels that are not exported do not appear in the object.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

FORMAT = "sra8-obj"
VERSION = 2
SECTION_TYPES = ("code", "data", "bss")
RELOC_TYPES = ("IMM16", "ABS16")
RE_LABEL = re.compile(r"(code|data|bss)(?::([A-Za-z_][A-Za-z0-9_.]*))?")


class ObjError(Exception):
    pass


@dataclass
class Section:
    type: str
    name: str
    size: int = 0
    data: bytearray | None = None       # None for bss

    @property
    def label(self) -> str:
        return self.type + (":" + self.name if self.name else "")


@dataclass
class Export:
    name: str
    section: int                        # index into Object.sections
    offset: int


@dataclass
class Reloc:
    section: int                        # the place to patch: section index ...
    offset: int                         # ... and offset in it
    type: str                           # IMM16 | ABS16
    target: int | None = None           # address from: a section of this object ...
    index: int = 0                      # ... at this offset (may lie outside it)
    symbol: str | None = None           # ... or an imported name
    addend: int = 0                     # added to the imported address


@dataclass
class Object:
    source: str
    sections: list[Section] = field(default_factory=list)
    exports: list[Export] = field(default_factory=list)
    relocations: list[Reloc] = field(default_factory=list)

    def export(self, name: str) -> Export | None:
        for e in self.exports:
            if e.name == name:
                return e
        return None

    def imports(self) -> list[str]:
        """The imported names, in order of first use."""
        out: list[str] = []
        for r in self.relocations:
            if r.symbol is not None and r.symbol not in out:
                out.append(r.symbol)
        return out

    # ---- serialisation -------------------------------------------------

    def to_json(self) -> str:
        secs = []
        for s in self.sections:
            d: dict = {"section": s.label, "size": s.size}
            if s.data is not None:
                d["data"] = s.data.hex().upper()
            secs.append(d)
        relocs = []
        for r in self.relocations:
            d = {"section": self.sections[r.section].label, "offset": r.offset, "type": r.type}
            if r.symbol is not None:
                d["import"] = r.symbol
                d["addend"] = r.addend
            else:
                d["from"] = self.sections[r.target].label
                d["index"] = r.index
            relocs.append(d)
        doc = {
            "format": FORMAT,
            "version": VERSION,
            "source": self.source,
            "sections": secs,
            "exports": [{"name": e.name, "section": self.sections[e.section].label, "offset": e.offset}
                        for e in self.exports],
            "relocations": relocs,
        }
        return _dump(doc)


def _dump(doc: dict) -> str:
    """JSON with one list element per line: readable and diff-friendly."""
    parts = ["{"]
    keys = list(doc)
    for i, k in enumerate(keys):
        v = doc[k]
        comma = "," if i < len(keys) - 1 else ""
        if isinstance(v, list) and v and isinstance(v[0], dict):
            parts.append("  %s: [" % json.dumps(k))
            for j, e in enumerate(v):
                parts.append("    %s%s" % (json.dumps(e, ensure_ascii=False), "," if j < len(v) - 1 else ""))
            parts.append("  ]%s" % comma)
        else:
            parts.append("  %s: %s%s" % (json.dumps(k), json.dumps(v, ensure_ascii=False), comma))
    parts.append("}")
    return "\n".join(parts) + "\n"


def _get(d: dict, key: str, kind: type, where: str):
    if not isinstance(d, dict) or key not in d or not isinstance(d[key], kind) \
            or (kind is int and isinstance(d[key], bool)):
        raise ObjError("%s: missing or invalid '%s'" % (where, key))
    return d[key]


def parse_label(label: str, where: str) -> tuple[str, str]:
    m = RE_LABEL.fullmatch(label)
    if not m:
        raise ObjError("%s: bad section '%s'" % (where, label))
    return m.group(1), m.group(2) or ""


def from_json(text: str, path: str = "<object>") -> Object:
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise ObjError("%s: not an object file (%s)" % (path, e))
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ObjError("%s: not an sra8 object file" % path)
    if doc.get("version") != VERSION:
        raise ObjError("%s: unsupported object version %r (expected %d)" % (path, doc.get("version"), VERSION))
    obj = Object(source=str(doc.get("source", path)))
    index: dict[str, int] = {}
    for i, d in enumerate(doc.get("sections", [])):
        where = "%s: section %d" % (path, i)
        label = _get(d, "section", str, where)
        stype, name = parse_label(label, where)
        if label in index:
            raise ObjError("%s: section '%s' listed twice" % (where, label))
        size = _get(d, "size", int, where)
        data = None
        if stype != "bss":
            try:
                data = bytearray.fromhex(_get(d, "data", str, where))
            except ValueError:
                raise ObjError("%s: bad data" % where)
            if len(data) != size:
                raise ObjError("%s: data is %d bytes, size says %d" % (where, len(data), size))
        index[label] = len(obj.sections)
        obj.sections.append(Section(stype, name, size, data))

    def section(d: dict, key: str, where: str) -> int:
        label = _get(d, key, str, where)
        if label not in index:
            raise ObjError("%s: unknown section '%s'" % (where, label))
        return index[label]

    for i, d in enumerate(doc.get("exports", [])):
        where = "%s: export %d" % (path, i)
        obj.exports.append(Export(_get(d, "name", str, where), section(d, "section", where),
                                  _get(d, "offset", int, where)))
    for i, d in enumerate(doc.get("relocations", [])):
        where = "%s: relocation %d" % (path, i)
        r = Reloc(section(d, "section", where), _get(d, "offset", int, where), _get(d, "type", str, where))
        if r.type not in RELOC_TYPES:
            raise ObjError("%s: bad type '%s'" % (where, r.type))
        if "import" in d:
            r.symbol = _get(d, "import", str, where)
            r.addend = _get(d, "addend", int, where)
        else:
            r.target = section(d, "from", where)
            r.index = _get(d, "index", int, where)
        width = 4 if r.type == "IMM16" else 2
        if r.offset < 0 or r.offset + width > obj.sections[r.section].size or obj.sections[r.section].data is None:
            raise ObjError("%s: offset outside the section" % where)
        obj.relocations.append(r)
    return obj


def read(path: str) -> Object:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return from_json(f.read(), path)
    except OSError as e:
        raise ObjError("cannot read '%s': %s" % (path, e.strerror))


def write(path: str, obj: Object) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(obj.to_json())


def patch(data: bytearray, offset: int, rtype: str, value: int) -> None:
    """Write a relocated 16 bit value into section bytes."""
    value &= 0xFFFF
    if rtype == "IMM16":
        data[offset + 2] = value >> 8
        data[offset + 3] = value & 0xFF
    elif rtype == "ABS16":
        data[offset] = value & 0xFF
        data[offset + 1] = value >> 8
    else:
        raise ObjError("unknown relocation type '%s'" % rtype)
