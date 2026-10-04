"""Two-pass assembler: source lines -> relocatable object (spec Section 3).

Pass 1 parses every statement, assigns section offsets and collects labels,
imports and exports.  Pass 2 encodes instructions and data and turns every
label reference into a relocation, because addresses exist only after
linking: a label of this file becomes "section + index", an imported name
stays a name.  Only exported labels go into the object; the rest, and the
source lines, are kept here for the listing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import isa
from ..obj import Export, Object, Reloc, Section
from .parser import (IDENT, RE_IDENT, RE_LABEL_DEF, Imm, LabelRef, Reg, parse_operand,
                     parse_value, split_operands, unescape)
from .preprocess import AsmError

MAX_ERRORS = 20

DATA_WIDTHS = {".byte": 1, ".word": 1, ".dword": 2, ".qword": 4, ".addr": 2}
SECTION_DIRECTIVES = {".code": "code", ".data": "data", ".bss": "bss"}

# Directives of other assemblers, or of earlier versions of this one,
# that deliberately do not exist (spec 3.10).
REMOVED = {
    ".org": "placement is done by the linker script",
    ".align": "placement is done by the linker script",
    ".balign": "placement is done by the linker script",
    ".global": "use .export",
    ".globl": "use .export",
    ".extern": "use .import",
    ".weak": "weak symbols do not exist",
    ".equ": "use !DEFINE for named constants",
    ".set": "use !DEFINE for named constants",
    ".section": "use .code, .data or .bss with an optional name",
    ".text": "use .code",
    ".rodata": "use .data with a name, e.g. '.data rodata'",
    ".incbin": "not supported",
    ".fill": "use .res in .code or .data for zero bytes",
    ".space": "use .res",
}

UNIMPLEMENTED = ("movs", "mvn", "mvns", "nop", "ret", "call", "halt", "push", "pop", "jmp")


@dataclass
class Item:
    """One statement that occupies section space."""
    kind: str                   # instr | data | res
    where: str
    section: int
    offset: int
    size: int
    text: str
    order: int                  # source order, for .b / .f
    mnemonic: str = ""
    cond: int = 0
    operands: list = field(default_factory=list)
    values: list = field(default_factory=list)      # data: (width, operand)
    raw: bytes = b""                                # data: string bytes


@dataclass
class ListLine:
    """One listed statement, for the assembler listing."""
    section: int
    offset: int
    size: int
    text: str
    kind: str


class Assembler:
    def __init__(self, source: str) -> None:
        self.source = source
        self.obj = Object(source=source)
        self.sec_index: dict[tuple[str, str], int] = {}
        self.cur = -1
        self.items: list[Item] = []
        self.labels: dict[str, tuple[int, int, str]] = {}       # name -> (section, offset, where)
        self.locals: dict[str, list[tuple[int, int, int]]] = {}  # name -> [(order, section, offset)]
        self.imports: dict[str, str] = {}                       # name -> where
        self.exports: dict[str, str] = {}
        self.used_imports: list[str] = []                       # in order of first use
        self.lines: list[ListLine] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    # ---- helpers ---------------------------------------------------------

    def error(self, e: AsmError, where: str) -> None:
        if e.where is None:
            e.where = where
        self.errors.append(str(e))
        if len(self.errors) >= MAX_ERRORS:
            raise AsmError("too many errors, stopping")

    def section(self, stype: str, name: str) -> int:
        key = (stype, name)
        if key not in self.sec_index:
            self.sec_index[key] = len(self.obj.sections)
            self.obj.sections.append(Section(stype, name, 0, None if stype == "bss" else bytearray()))
        return self.sec_index[key]

    @property
    def sec(self) -> Section:
        """The current section.  The unnamed code section that is current
        before the first section directive is created on first use only."""
        if self.cur < 0:
            self.cur = self.section("code", "")
        return self.obj.sections[self.cur]

    # ---- pass 1 ----------------------------------------------------------

    def pass1(self, lines: list[tuple[str, int, str]]) -> None:
        for order, (path, line_no, text) in enumerate(lines):
            where = "%s:%d" % (path, line_no)
            try:
                self.statement(order, where, text)
            except AsmError as e:
                self.error(e, where)

    def statement(self, order: int, where: str, text: str) -> None:
        while True:
            m = RE_LABEL_DEF.match(text)
            if not m:
                break
            self.define_label(m.group(2), bool(m.group(1)), order, where)
            text = text[m.end():]
        if not text:
            return
        parts = text.split(None, 1)
        word = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""
        if word.startswith("."):
            self.directive(word, rest, order, where, text)
        else:
            self.instruction(word, rest, order, where, text)

    def define_label(self, name: str, local: bool, order: int, where: str) -> None:
        size = self.sec.size
        if local:
            self.locals.setdefault(name, []).append((order, self.cur, size))
            return
        if name in self.labels:
            raise AsmError("label '%s' already defined at %s" % (name, self.labels[name][2]))
        self.labels[name] = (self.cur, size, where)

    def add_item(self, item: Item) -> None:
        if item.offset + item.size > isa.ADDR_SPACE:
            raise AsmError("section %s grows beyond 64 KiB" % self.sec.label)
        self.items.append(item)
        self.sec.size += item.size

    def directive(self, word: str, rest: str, order: int, where: str, text: str) -> None:
        if word in REMOVED:
            raise AsmError("'%s' does not exist: %s" % (word, REMOVED[word]))
        if word in SECTION_DIRECTIVES:
            if rest and not RE_IDENT.fullmatch(rest):
                raise AsmError("'%s' takes an optional section name, got '%s'" % (word, rest))
            self.cur = self.section(SECTION_DIRECTIVES[word], rest)
            return
        if word in (".import", ".export"):
            names = split_operands(rest)
            if not names:
                raise AsmError("'%s' needs at least one name" % word)
            table = self.imports if word == ".import" else self.exports
            for n in names:
                if not RE_IDENT.fullmatch(n):
                    raise AsmError("bad name '%s'" % n)
                if n in table:
                    self.warnings.append("%s: '%s' is already %sed" % (where, n, word[1:]))
                table.setdefault(n, where)
            return
        ops = split_operands(rest)
        stype = self.sec.type
        cur, offset = self.cur, self.sec.size
        if word == ".res":
            if len(ops) != 1:
                raise AsmError("'.res' takes 1 operand, got %d" % len(ops))
            v = parse_value(ops[0])
            if not isinstance(v, Imm) or not 0 <= v.value <= isa.ADDR_SPACE:
                raise AsmError("'.res' needs a size 0 .. 65536")
            self.add_item(Item("res", where, cur, offset, v.value, text, order))
            return
        if stype == "bss":
            raise AsmError("only .res is allowed in a .bss section")
        item = Item("data", where, cur, offset, 0, text, order)
        if word in DATA_WIDTHS:
            width = DATA_WIDTHS[word]
            if not ops:
                raise AsmError("'%s' needs at least one value" % word)
            for t in ops:
                v = parse_value(t)
                if isinstance(v, LabelRef) and word != ".addr":
                    raise AsmError("label reference not allowed in '%s', use .addr" % word)
                item.values.append((width, v))
            item.size = width * len(ops)
        elif word in (".ascii", ".asciz"):
            if len(ops) != 1:
                raise AsmError("'%s' takes 1 operand, got %d" % (word, len(ops)))
            s = ops[0]
            if len(s) < 2 or s[0] != '"' or s[-1] != '"':
                raise AsmError("'%s' needs a \"string\"" % word)
            s = unescape(s[1:-1]) + ("\0" if word == ".asciz" else "")
            try:
                item.raw = s.encode("latin-1")
            except UnicodeEncodeError:
                raise AsmError("string contains characters outside 8 bit range")
            item.size = len(item.raw)
        else:
            raise AsmError("unknown directive '%s'" % word)
        self.add_item(item)

    def instruction(self, word: str, rest: str, order: int, where: str, text: str) -> None:
        mnemonic, dot, cond = word.lower().partition(".")
        if mnemonic not in isa.INSTRUCTIONS:
            if mnemonic in UNIMPLEMENTED:
                raise AsmError("'%s' is not an SRA-8 instruction (there are no pseudo-instructions)" % mnemonic)
            raise AsmError("unknown instruction '%s'" % word)
        if dot and cond not in isa.CONDITIONS:
            raise AsmError("unknown condition '%s'" % cond)
        sec = self.sec
        if sec.type != "code":
            raise AsmError("instruction in a .%s section" % self.sec.type)
        if self.sec.size % isa.INSTR_SIZE:
            raise AsmError("instruction at unaligned offset %d of section %s; pad the preceding data "
                           "to a multiple of 4 bytes or move it to a .data section" % (self.sec.size, self.sec.label))
        ins = isa.INSTRUCTIONS[mnemonic]
        ops = [parse_operand(t) for t in split_operands(rest)]
        if len(ops) != ins.fmt.n_operands:
            n = ins.fmt.n_operands
            raise AsmError("'%s' takes %d operand%s, got %d" % (mnemonic, n, "" if n == 1 else "s", len(ops)))
        item = Item("instr", where, self.cur, sec.size, isa.INSTR_SIZE, text, order,
                    mnemonic=mnemonic, cond=isa.CONDITIONS[cond] if dot else 0, operands=ops)
        self.check_operands(item, ins)
        self.add_item(item)

    def check_operands(self, item: Item, ins: isa.Instr) -> None:
        widths = list(ins.fmt.regs) + ([ins.fmt.src] if ins.fmt.src else [])
        for i, (op, bits) in enumerate(zip(item.operands, widths)):
            is_src = ins.fmt.src and i == len(widths) - 1
            if isinstance(op, Reg):
                if op.pair != (bits == 16):
                    want = "a 16 bit register pair (r%da)" % op.n if bits == 16 else "an 8 bit register (r%d)" % op.n
                    raise AsmError("operand %d of '%s' must be %s, got 'r%d%s'"
                                   % (i + 1, ins.mnemonic, want, op.n, "a" if op.pair else ""))
                if op.pair and op.n == 15:
                    self.warnings.append("%s: r15a has no high register, the high byte wraps to r0" % item.where)
            elif not is_src:
                raise AsmError("operand %d of '%s' must be a register" % (i + 1, ins.mnemonic))
            elif isinstance(op, LabelRef) and ins.fmt.imm_width != 16:
                raise AsmError("'%s' takes %s, a label reference is not allowed"
                               % (ins.mnemonic, "a signed 12 bit offset" if ins.fmt.imm_signed
                                  else "an 8 bit immediate"))
            elif isinstance(op, Imm):
                try:
                    isa.fit_imm(ins.fmt, op.value)
                except isa.EncodeError as e:
                    raise AsmError(str(e))

    # ---- pass 2 ----------------------------------------------------------

    def check_linkage(self) -> None:
        for name, where in self.imports.items():
            if name in self.labels:
                self.errors.append("%s: '%s' is imported but also defined in this file" % (where, name))
        for name, where in self.exports.items():
            if name in self.imports:
                self.errors.append("%s: '%s' is imported, it cannot be exported" % (where, name))
            elif name not in self.labels:
                hint = " (local labels cannot be exported)" if name in self.locals else ""
                self.errors.append("%s: exported label '%s' is not defined%s" % (where, name, hint))

    def resolve(self, ref: LabelRef, item: Item) -> tuple[str | None, int | None, int]:
        """-> (imported name, None, addend) or (None, section, index) of a relocation."""
        if ref.direction is None:
            if ref.name in self.labels:
                sec, off, _ = self.labels[ref.name]
                return None, sec, off + ref.offset
            if ref.name in self.imports:
                if ref.name not in self.used_imports:
                    self.used_imports.append(ref.name)
                return ref.name, None, ref.offset
            if ref.name in self.locals:
                raise AsmError("undefined label '%s' (a local label: use .b =%s or .f =%s)" % (ref.name, ref.name, ref.name))
            raise AsmError("undefined name '%s' (add '.import %s' if it is defined in another file)" % (ref.name, ref.name))
        defs = self.locals.get(ref.name, [])
        if ref.direction == "b":
            found = [d for d in defs if d[0] <= item.order]
            pick = found[-1] if found else None
        else:
            found = [d for d in defs if d[0] > item.order]
            pick = found[0] if found else None
        if pick is None:
            raise AsmError("no local label '%s' %s this line" % (ref.name, "before" if ref.direction == "b" else "after"))
        return None, pick[1], pick[2] + ref.offset

    def add_reloc(self, item: Item, at: int, rtype: str, ref: LabelRef) -> int:
        """Record the relocation; the field holds the index or addend until linking."""
        symbol, target, value = self.resolve(ref, item)
        if symbol is not None:
            self.obj.relocations.append(Reloc(item.section, at, rtype, symbol=symbol, addend=value))
        else:
            self.obj.relocations.append(Reloc(item.section, at, rtype, target=target, index=value))
        return value & 0xFFFF

    def encode_instr(self, item: Item) -> bytes:
        ins = isa.INSTRUCTIONS[item.mnemonic]
        opcode = ins.opcode
        args = [0, 0, 0]
        imm = 0
        n = ins.fmt.n_operands
        for i, op in enumerate(item.operands):
            is_src = ins.fmt.src and i == n - 1
            if isinstance(op, Reg):
                args[i] = op.n
            elif isinstance(op, Imm):
                opcode |= 1
                imm = isa.fit_imm(ins.fmt, op.value)
            elif isinstance(op, LabelRef) and is_src:
                opcode |= 1
                imm = self.add_reloc(item, item.offset, "IMM16", op)
        return isa.encode(item.cond, opcode, tuple(args), imm)

    def encode_data(self, item: Item) -> bytes:
        if item.raw:
            return item.raw
        out = bytearray()
        for width, v in item.values:
            if isinstance(v, LabelRef):
                value = self.add_reloc(item, item.offset + len(out), "ABS16", v)
            else:
                value = isa.fit(v.value, 8 * width)
            out += value.to_bytes(width, "little")
        return bytes(out)

    def pass2(self) -> None:
        self.check_linkage()
        for item in self.items:
            try:
                if item.kind == "instr":
                    data = self.encode_instr(item)
                elif item.kind == "data":
                    data = self.encode_data(item)
                else:
                    data = bytes(item.size)
            except (AsmError, isa.EncodeError) as e:
                err = e if isinstance(e, AsmError) else AsmError(str(e))
                self.error(err, item.where)
                continue
            sec = self.obj.sections[item.section]
            if sec.data is not None:
                sec.data += data
            self.lines.append(ListLine(item.section, item.offset, item.size, item.text, item.kind))
        for name, where in self.imports.items():
            if name not in self.used_imports and name not in self.labels:
                self.warnings.append("%s: imported name '%s' is never used" % (where, name))

    def build(self) -> Object:
        for name, (sec, off, _) in self.labels.items():
            if name in self.exports:
                self.obj.exports.append(Export(name, sec, off))
        return self.obj


def assemble(lines: list[tuple[str, int, str]], source: str) -> tuple[Object, list[str], list[str], Assembler]:
    """-> (object, errors, warnings, assembler); the assembler feeds the listing."""
    a = Assembler(source)
    try:
        a.pass1(lines)
        if not a.errors:
            a.pass2()
    except AsmError as e:
        a.errors.append(str(e))
    obj = a.build() if not a.errors else a.obj
    return obj, a.errors, a.warnings, a


__all__ = ["assemble", "Assembler", "IDENT"]
