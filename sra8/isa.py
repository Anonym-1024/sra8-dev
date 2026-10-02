"""SRA-8 instruction set: the single source of truth for the toolchain.

Everything here was derived from the RTL in ``../sra-8-fpga/sra-8-fpga``:

* opcode numbers and operand order: ``control_unit_gen/control_rom_gen.c``
* bit fields of the instruction word: ``InstructionRegister.v``
* condition codes: ``ControlUnit.v``
* ALU operations and flags: ``ALU.v``
* microstep counts: ``control_rom.mem`` (position of the ``ucr`` step)

No other module may hardcode an opcode number.  Run ``python3 -m sra8.isa``
to print the reference tables as Markdown (``make docs`` writes them to
``docs/isa.md``).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

# --------------------------------------------------------------------------
# Instruction word
# --------------------------------------------------------------------------

INSTR_SIZE = 4              # bytes, stored big-endian
PAGE_SIZE = 256
ADDR_SPACE = 1 << 16

COND_SHIFT = 28             # [31:28]
OPCODE_SHIFT = 20           # [26:20], bit 27 unused
ARG1_SHIFT = 16             # [19:16]
ARG2_SHIFT = 12             # [15:12]
ARG3_SHIFT = 8              # [11:8]
ARG_SHIFTS = (ARG1_SHIFT, ARG2_SHIFT, ARG3_SHIFT)

FETCH_STEPS = 11            # microsteps of the fetch procedure
CLOCKS_PER_STEP = 4         # Clock.v: four phases per microstep
CLOCK_HZ = 12_000_000
UART_DIV = 104              # CPU.v: 12 MHz / 104 = 115 384 baud

# --------------------------------------------------------------------------
# Conditions (ControlUnit.v, cond_lut)
# --------------------------------------------------------------------------

CONDITIONS: dict[str, int] = {
    "al": 0, "eq": 1, "mi": 2, "vs": 3, "su": 4, "gu": 5, "ss": 6, "gs": 7,
    "nvr": 8, "ne": 9, "pl": 10, "vc": 11, "geu": 12, "seu": 13, "ges": 14, "ses": 15,
}
COND_NAMES: dict[int, str] = {v: k for k, v in CONDITIONS.items()}

COND_MEANING: dict[str, str] = {
    "al": "always", "eq": "Z", "mi": "N", "vs": "V",
    "su": "¬C (unsigned <)", "gu": "C ∧ ¬Z (unsigned >)",
    "ss": "N ⊕ V (signed <)", "gs": "¬(N ⊕ V) ∧ ¬Z (signed >)",
    "nvr": "never", "ne": "¬Z", "pl": "¬N", "vc": "¬V",
    "geu": "C (unsigned ≥)", "seu": "¬C ∨ Z (unsigned ≤)",
    "ges": "¬(N ⊕ V) (signed ≥)", "ses": "(N ⊕ V) ∨ Z (signed ≤)",
}

# --------------------------------------------------------------------------
# ALU operations (ALU.v)
# --------------------------------------------------------------------------

ALU_OPS: dict[str, int] = {
    "ADD": 0, "ADDC": 1, "SUB": 2, "SUBC": 3, "AND": 4, "OR": 5, "EOR": 6,
    "LSL": 7, "LSR": 8, "ASR": 9, "CSL": 10, "CSR": 11,
}

ALU_MEANING: dict[str, tuple[str, str, str]] = {
    # result, C, V
    "ADD": ("a + b", "carry out", "signed overflow"),
    "ADDC": ("a + b + C", "carry out", "signed overflow"),
    "SUB": ("a − b", "¬borrow (a ≥ b unsigned)", "signed overflow"),
    "SUBC": ("a − b − 1 + C", "¬borrow", "signed overflow"),
    "AND": ("a ∧ b", "0", "0"),
    "OR": ("a ∨ b", "0", "0"),
    "EOR": ("a ⊕ b", "0", "0"),
    "LSL": ("a << 1", "old a7", "0"),
    "LSR": ("a >> 1, logical", "old a0", "0"),
    "ASR": ("a >> 1, sign kept", "old a0", "0"),
    "CSL": ("{a[6:0], C}", "old a7", "0"),
    "CSR": ("{C, a[7:1]}", "old a0", "0"),
}

# --------------------------------------------------------------------------
# Operand formats
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Format:
    """Operand layout.  ``regs`` are the widths of the register operands
    that come before the source; ``src`` is the width of the last operand,
    which may be a register or an immediate (0 = no such operand)."""

    name: str
    regs: tuple[int, ...]
    src: int
    syntax: str

    @property
    def n_operands(self) -> int:
        return len(self.regs) + (1 if self.src else 0)

    @property
    def has_imm(self) -> bool:
        return self.src != 0


FORMATS: dict[str, Format] = {f.name: f for f in (
    Format("NONE", (), 0, ""),
    Format("RD", (8,), 0, "rD"),
    Format("RDA", (16,), 0, "rDa"),
    Format("SRC8", (), 8, "rS / #imm8"),
    Format("SRC16", (), 16, "rSa / #imm16"),
    Format("RD_SRC8", (8,), 8, "rD, rS / #imm8"),
    Format("RD_SRC16", (8,), 16, "rD, rSa / #imm16"),
    Format("RDA_SRC16", (16,), 16, "rDa, rSa / #imm16"),
    Format("ALU3", (8, 8), 8, "rD, rN, rM / #imm8"),
)}


@dataclass(frozen=True)
class Instr:
    mnemonic: str
    opcode: int             # register form; immediate form = opcode | 1
    fmt: Format
    steps: int              # microsteps of the body including the ucr step
    group: str
    meaning: str
    alu: str | None = None  # ALU operation, if any
    sets_flags: bool = False


def _i(m: str, op: int, fmt: str, steps: int, group: str, meaning: str,
       alu: str | None = None, flags: bool = False) -> Instr:
    return Instr(m, op, FORMATS[fmt], steps, group, meaning, alu, flags)


_G_REG = "Register and system register moves"
_G_MEM = "Memory"
_G_ALU = "Arithmetic and logic: rD = rN op (rM | imm8)"
_G_SHIFT = "Shifts by one bit: rD = op(rS | imm8)"
_G_FLAGS = "Flags only, result discarded"
_G_BR = "Control flow"
_G_IO = "I/O and other"

INSTRUCTIONS: dict[str, Instr] = {i.mnemonic: i for i in (
    _i("mov", 0, "RD_SRC8", 2, _G_REG, "rD ← src"),
    _i("mova", 2, "RDA_SRC16", 3, _G_REG, "rDa ← src"),
    _i("pcw", 4, "SRC16", 3, _G_REG, "PC ← src"),
    _i("pcr", 6, "RDA", 3, _G_REG, "rDa ← PC"),
    _i("xpcw", 8, "SRC16", 3, _G_REG, "current PC ← src (PC, or INTPC while interrupted)"),
    _i("xpcr", 10, "RDA", 3, _G_REG, "rDa ← current PC (address of the next instruction)"),
    _i("intpcw", 12, "SRC16", 3, _G_REG, "INTPC ← src"),
    _i("intpcr", 14, "RDA", 3, _G_REG, "rDa ← INTPC"),
    _i("psrw", 16, "SRC8", 2, _G_REG, "PSR ← src"),
    _i("psrr", 18, "RD", 2, _G_REG, "rD ← PSR"),
    _i("ptbrw", 20, "SRC16", 3, _G_REG, "PTBR ← src"),
    _i("ptbrr", 22, "RDA", 3, _G_REG, "rDa ← PTBR"),
    _i("intrw", 24, "SRC8", 2, _G_REG, "INTR ← 0 (the value is ignored)"),
    _i("intrr", 26, "RD", 2, _G_REG, "rD ← INTR"),

    _i("ldr", 28, "RD_SRC16", 6, _G_MEM, "rD ← mem[addr]"),
    _i("str", 30, "RD_SRC16", 6, _G_MEM, "mem[addr] ← rS  (source register first)"),

    _i("add", 32, "ALU3", 4, _G_ALU, "rD ← rN + src", "ADD"),
    _i("adds", 34, "ALU3", 4, _G_ALU, "rD ← rN + src, flags", "ADD", True),
    _i("addc", 36, "ALU3", 4, _G_ALU, "rD ← rN + src + C", "ADDC"),
    _i("addcs", 38, "ALU3", 4, _G_ALU, "rD ← rN + src + C, flags", "ADDC", True),
    _i("sub", 40, "ALU3", 4, _G_ALU, "rD ← rN − src", "SUB"),
    _i("subs", 42, "ALU3", 4, _G_ALU, "rD ← rN − src, flags", "SUB", True),
    _i("subc", 44, "ALU3", 4, _G_ALU, "rD ← rN − src − 1 + C", "SUBC"),
    _i("subcs", 46, "ALU3", 4, _G_ALU, "rD ← rN − src − 1 + C, flags", "SUBC", True),
    _i("and", 48, "ALU3", 4, _G_ALU, "rD ← rN ∧ src", "AND"),
    _i("ands", 50, "ALU3", 4, _G_ALU, "rD ← rN ∧ src, flags", "AND", True),
    _i("or", 52, "ALU3", 4, _G_ALU, "rD ← rN ∨ src", "OR"),
    _i("ors", 54, "ALU3", 4, _G_ALU, "rD ← rN ∨ src, flags", "OR", True),
    _i("eor", 56, "ALU3", 4, _G_ALU, "rD ← rN ⊕ src", "EOR"),
    _i("eors", 58, "ALU3", 4, _G_ALU, "rD ← rN ⊕ src, flags", "EOR", True),

    _i("lsl", 60, "RD_SRC8", 3, _G_SHIFT, "rD ← src << 1", "LSL"),
    _i("lsls", 62, "RD_SRC8", 3, _G_SHIFT, "rD ← src << 1, flags", "LSL", True),
    _i("lsr", 64, "RD_SRC8", 3, _G_SHIFT, "rD ← src >> 1", "LSR"),
    _i("lsrs", 66, "RD_SRC8", 3, _G_SHIFT, "rD ← src >> 1, flags", "LSR", True),
    _i("asr", 68, "RD_SRC8", 3, _G_SHIFT, "rD ← src >> 1, sign kept", "ASR"),
    _i("asrs", 70, "RD_SRC8", 3, _G_SHIFT, "rD ← src >> 1, sign kept, flags", "ASR", True),
    _i("csl", 72, "RD_SRC8", 3, _G_SHIFT, "rD ← {src[6:0], C}", "CSL"),
    _i("csls", 74, "RD_SRC8", 3, _G_SHIFT, "rD ← {src[6:0], C}, flags", "CSL", True),
    _i("csr", 76, "RD_SRC8", 3, _G_SHIFT, "rD ← {C, src[7:1]}", "CSR"),
    _i("csrs", 78, "RD_SRC8", 3, _G_SHIFT, "rD ← {C, src[7:1]}, flags", "CSR", True),

    _i("cmn", 80, "RD_SRC8", 4, _G_FLAGS, "flags of rN + src", "ADD", True),
    _i("addcd", 82, "RD_SRC8", 4, _G_FLAGS, "flags of rN + src + C", "ADDC", True),
    _i("cmp", 84, "RD_SRC8", 4, _G_FLAGS, "flags of rN − src", "SUB", True),
    _i("subcd", 86, "RD_SRC8", 4, _G_FLAGS, "flags of rN − src − 1 + C", "SUBC", True),
    _i("andd", 88, "RD_SRC8", 4, _G_FLAGS, "flags of rN ∧ src", "AND", True),
    _i("ord", 90, "RD_SRC8", 4, _G_FLAGS, "flags of rN ∨ src", "OR", True),
    _i("eord", 92, "RD_SRC8", 4, _G_FLAGS, "flags of rN ⊕ src", "EOR", True),
    _i("lsld", 94, "SRC8", 3, _G_FLAGS, "flags of src << 1", "LSL", True),
    _i("lsrd", 96, "SRC8", 3, _G_FLAGS, "flags of src >> 1", "LSR", True),
    _i("asrd", 98, "SRC8", 3, _G_FLAGS, "flags of src >> 1, sign kept", "ASR", True),
    _i("csld", 100, "SRC8", 3, _G_FLAGS, "flags of {src[6:0], C}", "CSL", True),
    _i("csrd", 102, "SRC8", 3, _G_FLAGS, "flags of {C, src[7:1]}", "CSR", True),

    _i("br", 104, "SRC16", 3, _G_BR, "current PC ← target"),
    _i("brl", 106, "RDA_SRC16", 5, _G_BR, "rLa ← address of next instruction; current PC ← target"),

    _i("ptr", 108, "RD", 2, _G_IO, "rD ← received UART byte; clears the port IRQ line"),
    _i("ptw", 110, "RD", 2, _G_IO, "send rS on the UART (no busy flag)"),
    _i("svc", 112, "NONE", 2, _G_IO, "supervisor call: enter interrupt mode"),
)}

GROUPS: tuple[str, ...] = (_G_REG, _G_MEM, _G_ALU, _G_SHIFT, _G_FLAGS, _G_BR, _G_IO)

# opcode (with the immediate bit) -> (instruction, immediate form?)
OPCODES: dict[int, tuple[Instr, bool]] = {}
for _ins in INSTRUCTIONS.values():
    OPCODES[_ins.opcode] = (_ins, False)
    if _ins.fmt.has_imm:
        OPCODES[_ins.opcode | 1] = (_ins, True)

UNDEFINED_OPCODES: tuple[int, ...] = tuple(op for op in range(128) if op not in OPCODES)


def cycles(ins: Instr) -> int:
    """Clock cycles of an executed instruction, fetch included."""
    return CLOCKS_PER_STEP * (FETCH_STEPS + ins.steps)


SKIPPED_CYCLES = CLOCKS_PER_STEP * (FETCH_STEPS + 1)

# --------------------------------------------------------------------------
# Encoding and decoding
# --------------------------------------------------------------------------


class EncodeError(Exception):
    pass


def fit(value: int, bits: int) -> int:
    """Accept -2**(bits-1) .. 2**bits - 1 and return the two's complement field."""
    if value < -(1 << (bits - 1)) or value >= (1 << bits):
        raise EncodeError("value %d does not fit in %d bits" % (value, bits))
    return value & ((1 << bits) - 1)


def encode(cond: int, opcode: int, args: tuple[int, int, int] = (0, 0, 0), imm: int = 0) -> bytes:
    """Assemble one instruction word.  ``imm`` is the raw 8 or 16 bit field."""
    word = (cond & 0xF) << COND_SHIFT | (opcode & 0x7F) << OPCODE_SHIFT
    for reg, shift in zip(args, ARG_SHIFTS):
        word |= (reg & 0xF) << shift
    word |= imm & 0xFFFF
    return word.to_bytes(INSTR_SIZE, "big")


@dataclass(frozen=True)
class Decoded:
    cond: int
    ins: Instr
    imm_form: bool
    regs: tuple[int, ...]   # register operands in source order (src register included)
    imm: int | None         # immediate value of the immediate form

    def operands(self, imm_text: str | None = None) -> list[str]:
        out = []
        widths = list(self.ins.fmt.regs) + ([self.ins.fmt.src] if self.ins.fmt.src else [])
        for i, width in enumerate(widths):
            is_src = self.ins.fmt.src and i == len(widths) - 1
            if is_src and self.imm_form:
                if imm_text is not None:
                    out.append(imm_text)
                else:
                    out.append("#0x%0*X" % (2 if width == 8 else 4, self.imm))
            else:
                out.append("r%d%s" % (self.regs[i], "a" if width == 16 else ""))
        return out

    def text(self, imm_text: str | None = None) -> str:
        name = self.ins.mnemonic + ("" if self.cond == 0 else "." + COND_NAMES[self.cond])
        ops = self.operands(imm_text)
        return name if not ops else "%-7s %s" % (name, ", ".join(ops))


def decode(data: bytes) -> Decoded | None:
    """Decode a 4 byte word.  Returns None unless the word is exactly what
    the assembler would produce (defined opcode, bit 27 clear, unused
    fields zero), so that disassembly always re-assembles byte for byte."""
    if len(data) != INSTR_SIZE:
        return None
    word = int.from_bytes(data, "big")
    cond = word >> COND_SHIFT & 0xF
    opcode = word >> OPCODE_SHIFT & 0x7F
    if word >> 27 & 1 or opcode not in OPCODES:
        return None
    ins, imm_form = OPCODES[opcode]
    fmt = ins.fmt
    n_regs = len(fmt.regs) + (1 if fmt.src and not imm_form else 0)
    regs = tuple(word >> ARG_SHIFTS[i] & 0xF for i in range(n_regs))
    imm = None
    if imm_form:
        imm = word & (0xFF if fmt.src == 8 else 0xFFFF)
    dec = Decoded(cond, ins, imm_form, regs, imm)
    if encode(cond, opcode, tuple(regs) + (0,) * (3 - len(regs)), imm or 0) != data:
        return None
    return dec


# --------------------------------------------------------------------------
# Markdown reference (docs/isa.md)
# --------------------------------------------------------------------------


def markdown() -> str:
    out = ["# SRA-8 instruction set", "",
           "Generated from the instruction table (`sra8/isa.py`, mirrored by `c/src/common/isa.c`) with `make docs`. Do not edit.", "",
           "## Instruction word", "",
           "32 bit, stored big-endian (the byte at the lowest address holds bits 31:24).", "",
           "| Bits | Field |", "|---|---|",
           "| 31:28 | condition |", "| 27 | unused, 0 |", "| 26:20 | opcode; bit 20 = immediate form |",
           "| 19:16 | arg1 |", "| 15:12 | arg2 |", "| 11:8 | arg3 |",
           "| 7:0 | imm8 |", "| 15:0 | imm16 (overlaps arg2 and arg3) |", "",
           "Register operands fill arg1, arg2, arg3 in the order they are written. "
           "`rNa` is the pair r(N+1):rN, low byte in rN; r15a wraps to r0 as the high byte.", "",
           "## Operand formats", "", "| Format | Operands |", "|---|---|"]
    for f in FORMATS.values():
        out.append("| %s | %s |" % (f.name, f.syntax or "—"))
    out += ["", "## Conditions", "",
            "Written as a suffix: `add.eq r1, r2, r3`. A false condition costs %d clocks and changes nothing." % SKIPPED_CYCLES,
            "", "| Code | Suffix | True when |", "|---|---|---|"]
    for name, code in CONDITIONS.items():
        out.append("| %d | `%s` | %s |" % (code, name, COND_MEANING[name]))
    out += ["", "## ALU operations", "", "Z = result is 0, N = bit 7 of the result for every operation.", "",
            "| Code | Operation | Result | C | V |", "|---|---|---|---|---|"]
    for name, code in ALU_OPS.items():
        r, c, v = ALU_MEANING[name]
        out.append("| %d | %s | %s | %s | %s |" % (code, name, r, c, v))
    out += ["", "## Instructions", "",
            "Cycles = %d × (%d fetch steps + steps), at %d MHz." % (CLOCKS_PER_STEP, FETCH_STEPS, CLOCK_HZ // 1_000_000)]
    for group in GROUPS:
        out += ["", "### " + group, "",
                "| Mnemonic | Operands | Reg | Imm | Steps | Cycles | Meaning |",
                "|---|---|---|---|---|---|---|"]
        for ins in INSTRUCTIONS.values():
            if ins.group != group:
                continue
            imm = str(ins.opcode | 1) if ins.fmt.has_imm else "—"
            out.append("| `%s` | %s | %d | %s | %d | %d | %s |" % (
                ins.mnemonic, ins.fmt.syntax or "—", ins.opcode, imm, ins.steps, cycles(ins), ins.meaning))
    out += ["", "## Undefined opcodes", "",
            ", ".join(str(o) for o in UNDEFINED_OPCODES) + ".", "",
            "Their microcode is all zero and never returns to fetch: executing one is destructive. "
            "The assembler cannot produce them.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    sys.stdout.write(markdown())
