"""Assembler listing (spec 3.9): section-relative offsets, before linking.

The object holds neither the source lines nor the labels that are not
exported, so the listing is made from the assembler's own state."""

from __future__ import annotations

from .assembler import Assembler


def listing(a: Assembler) -> str:
    obj = a.obj
    out = []
    for l in a.lines:
        sec = obj.sections[l.section]
        place = "%s+%04X" % (sec.label, l.offset)
        if l.kind == "res":
            out.append("%-16s %-24s %s" % (place, "(%d bytes)" % l.size, l.text))
            continue
        data = b"" if sec.data is None else bytes(sec.data[l.offset:l.offset + l.size])
        out.append("%-16s %-24s %s" % (place, " ".join("%02X" % b for b in data[:8]), l.text))
        for i in range(8, len(data), 8):
            out.append("%-16s %s" % ("%s+%04X" % (sec.label, l.offset + i),
                                     " ".join("%02X" % b for b in data[i:i + 8])))
    out += ["", "sections"]
    for s in obj.sections:
        out.append("  %-16s %5d bytes" % (s.label, s.size))
    out += ["", "labels"]
    labels = sorted(a.labels.items(), key=lambda kv: (kv[1][0], kv[1][1]))
    for name, (sec, off, _) in labels:
        out.append("  %-16s %s%s" % ("%s+%04X" % (obj.sections[sec].label, off), name,
                                     "  (exported)" if name in a.exports else ""))
    out += ["", "imports"]
    out += ["  " + n for n in obj.imports()]
    out += ["", "relocations"]
    for r in obj.relocations:
        if r.symbol is not None:
            source, value = r.symbol, r.addend
        else:
            source, value = "[%s]" % obj.sections[r.target].label, r.index
        out.append("  %-16s %-6s %s %s 0x%X" % ("%s+%04X" % (obj.sections[r.section].label, r.offset),
                                                r.type, source, "+" if value >= 0 else "-", abs(value)))
    return "\n".join(out) + "\n"
