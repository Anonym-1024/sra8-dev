"""sra8-objdump: disassemble objects and images; dump symbols and relocations.

Disassembly is written in the syntax of the assembler, so it assembles
again: addresses and bytes go into ``;`` comments, words that are not
exactly what the assembler would produce are written as ``.byte``.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import isa
from . import obj as objfile
from .obj import Object


# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------

def read_mem(text: str, path: str) -> tuple[int, bytes]:
    mem: dict[int, int] = {}
    addr = 0
    for line_no, line in enumerate(text.split("\n"), 1):
        line = line.split("//", 1)[0]
        for tok in line.split():
            if tok.startswith("@"):
                addr = int(tok[1:], 16)
                continue
            try:
                mem[addr] = int(tok, 16) & 0xFF
            except ValueError:
                raise objfile.ObjError("%s:%d: bad byte '%s'" % (path, line_no, tok))
            addr += 1
    if not mem:
        return 0, b""
    lo, hi = min(mem), max(mem)
    return lo, bytes(mem.get(a, 0) for a in range(lo, hi + 1))


def load(path: str) -> Object | tuple[int, bytes]:
    with open(path, "rb") as f:
        raw = f.read()
    head = raw.lstrip()[:1]
    if head == b"{":
        try:
            if json.loads(raw.decode("utf-8")).get("format") == objfile.FORMAT:
                return objfile.from_json(raw.decode("utf-8"), path)
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            pass
    if path.endswith(".mem") or head == b"@":
        return read_mem(raw.decode("latin-1"), path)
    return 0, raw


# --------------------------------------------------------------------------
# Disassembly
# --------------------------------------------------------------------------

def _comment(addr: int, data: bytes) -> str:
    return "; %04X  %s" % (addr, " ".join("%02X" % b for b in data))


def _line(text: str, addr: int, data: bytes) -> str:
    return "        %-34s %s" % (text, _comment(addr, data))


def _bytes_directive(data: bytes) -> str:
    return ".byte   " + ", ".join("0x%02X" % b for b in data)


def disassemble_image(start: int, data: bytes, lo: int | None = None, hi: int | None = None) -> str:
    lo = start if lo is None else max(lo, start)
    hi = start + len(data) if hi is None else min(hi, start + len(data))
    out = ["; disassembly of 0x%04X .. 0x%04X" % (lo, max(lo, hi - 1)), "", ".code"]
    a = lo
    while a < hi:
        if (a - start) % isa.INSTR_SIZE == 0 and a + isa.INSTR_SIZE <= hi:
            word = data[a - start:a - start + isa.INSTR_SIZE]
            dec = isa.decode(word)
            if dec is not None:
                out.append(_line(dec.text(), a, word))
            else:
                out.append(_line(_bytes_directive(word) + "  ; not an instruction", a, word))
            a += isa.INSTR_SIZE
        else:
            n = min(hi - a, isa.INSTR_SIZE - (a - start) % isa.INSTR_SIZE)
            chunk = data[a - start:a - start + n]
            out.append(_line(_bytes_directive(chunk), a, chunk))
            a += n
    return "\n".join(out) + "\n"


class ObjectPrinter:
    """Turns an object back into assembly source.

    Only exported labels have names in the object.  Every other address
    is "section + index"; such targets get the generated names
    L<section>_<offset>, at the nearest place inside the section."""

    def __init__(self, o: Object) -> None:
        self.o = o
        self.labels: dict[tuple[int, int], list[str]] = {}
        for e in o.exports:
            self.labels.setdefault((e.section, e.offset), []).append(e.name)
        for r in o.relocations:
            if r.target is not None:
                key = self.anchor(r)
                if key not in self.labels:
                    self.labels[key] = ["L%d_%04X" % key]
        self.relocs = {(r.section, r.offset): r for r in o.relocations}

    def anchor(self, r: objfile.Reloc) -> tuple[int, int]:
        """A label position for a section relocation: its index, kept inside the section."""
        return r.target, min(max(r.index, 0), self.o.sections[r.target].size)

    def ref(self, r: objfile.Reloc) -> str:
        if r.symbol is not None:
            name, addend = r.symbol, r.addend
        else:
            key = self.anchor(r)
            name, addend = self.labels[key][0], r.index - key[1]
        if addend > 0:
            return "=%s + %d" % (name, addend)
        if addend < 0:
            return "=%s - %d" % (name, -addend)
        return "=%s" % name

    def section(self, idx: int) -> list[str]:
        s = self.o.sections[idx]
        out = ["", ".%s%s" % (s.type, " " + s.name if s.name else "")]
        breaks = sorted(off for (sec, off) in self.labels if sec == idx)
        if s.data is None:
            pos = 0
            for off in breaks + ([] if s.size in breaks else [s.size]):
                if off > pos:
                    out.append("        .res    %d" % (off - pos))
                    pos = off
                out += ["%s:" % n for n in self.labels.get((idx, off), [])]
            return out
        data = bytes(s.data)
        pos = 0
        while pos <= len(data):
            out += ["%s:" % n for n in self.labels.get((idx, pos), [])]
            if pos == len(data):
                break
            nxt = min([b for b in breaks if b > pos] + [len(data)])
            r = self.relocs.get((idx, pos))
            inside = [o for (sec, o), rr in self.relocs.items()
                      if sec == idx and pos <= o < pos + 4 and not (o == pos and rr.type == "IMM16")]
            if s.type == "code" and pos % 4 == 0 and pos + 4 <= nxt and not inside:
                word = data[pos:pos + 4]
                dec = isa.decode(word)
                if dec is not None:
                    imm_text = None
                    if r is not None and r.type == "IMM16":
                        imm_text = self.ref(r)
                    out.append(_line(dec.text(imm_text), pos, word))
                    pos += 4
                    continue
            if r is not None and r.type == "ABS16":
                out.append(_line(".addr   " + self.ref(r), pos, data[pos:pos + 2]))
                pos += 2
                continue
            stops = [nxt, pos + 8] + [off for (sec, off) in self.relocs if sec == idx and off > pos]
            if s.type == "code":
                stops.append((pos // 4 + 1) * 4)
            end = min(stops)
            out.append(_line(_bytes_directive(data[pos:end]), pos, data[pos:end]))
            pos = end
        return out

    def text(self) -> str:
        out = ["; disassembly of %s" % self.o.source]
        imports = self.o.imports()
        if imports:
            out.append(".import %s" % ", ".join(imports))
        if self.o.exports:
            out.append(".export %s" % ", ".join(e.name for e in self.o.exports))
        for i in range(len(self.o.sections)):
            out += self.section(i)
        return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# Dumps
# --------------------------------------------------------------------------

def hexdump(start: int, data: bytes, title: str) -> str:
    out = [title]
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append("  %04X  %-48s %s" % (start + i, " ".join("%02X" % b for b in chunk), text))
    return "\n".join(out) + "\n"


def symbols_text(o: Object) -> str:
    out = ["sections"]
    for i, s in enumerate(o.sections):
        out.append("  [%d] %-16s %5d bytes" % (i, s.label, s.size))
    out += ["", "exports"]
    for e in o.exports:
        out.append("  %-16s %s" % ("%s+%04X" % (o.sections[e.section].label, e.offset), e.name))
    out += ["", "imports"] + ["  " + n for n in o.imports()]
    return "\n".join(out) + "\n"


def relocs_text(o: Object) -> str:
    out = ["relocations"]
    for r in o.relocations:
        if r.symbol is not None:
            source = "%s %+d" % (r.symbol, r.addend)
        else:
            source = "[%s] %+d" % (o.sections[r.target].label, r.index)
        out.append("  %-16s %-6s %s" % ("%s+%04X" % (o.sections[r.section].label, r.offset), r.type, source))
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sra8-objdump", description="SRA-8 object and image dumper")
    ap.add_argument("file", help=".o object, .bin or .mem image")
    ap.add_argument("-d", "--disassemble", action="store_true")
    ap.add_argument("-s", "--hex", action="store_true", help="hex dump")
    ap.add_argument("-t", "--symbols", action="store_true", help="sections, exports, imports")
    ap.add_argument("-r", "--relocs", action="store_true")
    ap.add_argument("--start", type=lambda s: int(s, 0), help="first address (images)")
    ap.add_argument("--end", type=lambda s: int(s, 0), help="address after the last one (images)")
    args = ap.parse_args(argv)
    if not (args.disassemble or args.hex or args.symbols or args.relocs):
        args.disassemble = True
    try:
        what = load(args.file)
    except (OSError, objfile.ObjError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    parts = []
    if isinstance(what, Object):
        if args.symbols:
            parts.append(symbols_text(what))
        if args.relocs:
            parts.append(relocs_text(what))
        if args.hex:
            for s in what.sections:
                if s.data is not None:
                    parts.append(hexdump(0, bytes(s.data), "section " + s.label))
        if args.disassemble:
            parts.append(ObjectPrinter(what).text())
    else:
        start, data = what
        if args.symbols or args.relocs:
            print("note: an image has no symbols or relocations", file=sys.stderr)
        if args.hex:
            parts.append(hexdump(start, data, "image"))
        if args.disassemble:
            parts.append(disassemble_image(start, data, args.start, args.end))
    sys.stdout.write("\n".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
