"""Linker outputs (spec 5.4): bin, mem, ihex and the map."""

from __future__ import annotations

from .layout import Result


class OutputError(Exception):
    pass


def mem_text(res: Result, mem_size: int) -> str:
    """Verilog $readmemh image, exactly the legacy program.mem format."""
    if res.image and res.image_start != 0:
        raise OutputError("a .mem image must start at address 0, this one starts at 0x%04X" % res.image_start)
    if len(res.image) > mem_size:
        raise OutputError("the image is %d bytes, the .mem size is %d (see --mem-size)" % (len(res.image), mem_size))
    mem = res.image + bytes(mem_size - len(res.image))
    lines = ["@0000"]
    for i in range(0, len(mem), 4):
        lines.append(" ".join("%02X" % b for b in mem[i:i + 4]))
    return "\n".join(lines) + "\n"


def ihex_text(res: Result) -> str:
    lines = []
    for i in range(0, len(res.image), 16):
        chunk = res.image[i:i + 16]
        addr = res.image_start + i
        rec = bytes([len(chunk), addr >> 8, addr & 0xFF, 0]) + chunk
        lines.append(":" + rec.hex().upper() + "%02X" % (-sum(rec) & 0xFF))
    lines.append(":00000001FF")
    return "\n".join(lines) + "\n"


def map_text(res: Result, script_path: str) -> str:
    out = ["Linker script: %s" % script_path, "",
           "Memory regions",
           "  %-12s %-6s %-6s %7s %7s %7s" % ("name", "start", "last", "size", "used", "free")]
    for r in res.regions:
        out.append("  %-12s 0x%04X 0x%04X %7d %7d %7d" % (r.name, r.start, r.start + r.size - 1,
                                                          r.size, r.used, r.size - r.used))
    out += ["", "Image", "  0x%04X .. 0x%04X, %d bytes" % (
        res.image_start, res.image_start + max(len(res.image), 1) - 1, len(res.image))]
    out += ["", "Sections",
            "  %-6s %-6s %7s  %-20s %s" % ("start", "last", "size", "section", "object")]
    for c in res.contributions:
        label = c.stype + (":" + c.name if c.name else "")
        last = "0x%04X" % (c.addr + c.size - 1) if c.size else "-"
        out.append("  0x%04X %-6s %7d  %-20s %s" % (c.addr, last, c.size, label, res.paths[c.obj]))
    out += ["", "Symbols"]
    for s in sorted(res.symbols, key=lambda s: (s.addr, s.name)):
        where = res.paths[s.obj] if s.obj is not None else "(script)"
        out.append("  0x%04X  %-24s %-8s %s" % (s.addr, s.name, s.kind, where))
    return "\n".join(out) + "\n"
