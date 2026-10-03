# SRA-8 Development Kit — Specification and Generation Prompt

This document is two things at once:

1. A **complete reference of the SRA-8 CPU** as implemented in the Verilog
   sources in `../sra-8-fpga/sra-8-fpga/` (the "RTL"), written for people who
   build tools for it, not hardware.
2. A **specification of the development kit** to be generated in this folder
   (`sra8-dev/`): an assembler, an object file format, a linker with
   linker-script support, a disassembler, and a test suite.

Everything in it was derived from reading the RTL, the microcode generators,
the two existing assemblers, the sample programs and `Instructions.xlsx`,
and from the author's change list (`Changes.txt`, applied 2026-09-29).
Where the sources contradict each other, or where a decision had to be made
that the sources do not settle, it is marked so that you can edit it.

## 0. How to read and edit this file

Markers used throughout:

| Marker | Meaning | What you should do |
|---|---|---|
| `[VERIFY]` | A fact read from the RTL that looks suspicious, or that conflicts with comments in the sample programs. | Confirm or correct. If the RTL will change, say so. |
| `[DECISION: default = …]` | A design choice the sources do not settle. A default was chosen so that generation can proceed without you. | Keep, or replace the default. |
| `[AUTHOR]` | A requirement stated by the author in `Changes.txt`. Binding; not a default. | Nothing, unless you changed your mind. |
| `[TODO]` | Information only you can supply. Generation proceeds with the stated fallback. | Fill in if you care. |

Rules for the generator (the model that turns this file into code):

- **The RTL wins.** If this document and the Verilog disagree, follow the
  Verilog and report the discrepancy in the final summary. Never "fix" the
  hardware description to match this file.
- **Read only** `../sra-8-fpga/sra-8-fpga/`. **Create only** inside
  `sra8-dev/`. Copying sample `.s` programs from the RTL folder into
  `sra8-dev/examples/` and `sra8-dev/tests/` is allowed and expected.
- Every `[AUTHOR]` item is binding. Every `[DECISION]` default is binding
  unless the user edited it.
- **Do not add features** that this document does not list. Several
  conveniences common in other toolchains were deliberately removed
  (Section 3.10 lists them); do not reintroduce them.
- Everything in Section 10 (Generation instructions) is the actual task.

---

## 1. Goals and deliverables

### 1.1 The pipeline

```
   a.s ──sra8-as──▶ a.o ─┐
   b.s ──sra8-as──▶ b.o ─┼──sra8-ld -T script.ld──▶ image.bin / image.mem / image.map
   …                     ┘
```

- **Assembly** (`.s`) is the source language.
- The **assembler** produces relocatable **object files** (`.o`).
- The **linker** combines objects, driven by a **linker script**, and emits
  the final **binary** plus derived formats.
- Building a whole program is done by a `Makefile` (or by hand) that calls
  the tools in turn; an example `Makefile` is part of the kit.

### 1.2 Tools to deliver

| Tool | Purpose |
|---|---|
| `sra8-as` | Assembler: `.s → .o`. |
| `sra8-ld` | Linker: objects + script → image and map file. |
| `sra8-objdump` | Disassemble objects and images, dump symbols/relocations. |

Also part of the kit: a VS Code extension (`vscode/sra8-lang`) with syntax
highlighting for assembly (`.s`) and linker scripts (`.ld`). Its grammar
is generated from the instruction table (`make vscode`) so the mnemonic
list cannot drift.

**Not part of the kit** `[AUTHOR]`: an archiver (`sra8-ar`), an emulator
(`sra8-emu`), an uploader (`sra8-upload`). Consequences:

- There are no static libraries. Shared code is a set of `.s` files that
  are assembled and listed on the linker command line like any other
  object.
- Nothing in the kit can execute SRA-8 code. Programs are verified
  on the FPGA. The test suite (Section 8) therefore checks *encodings and
  generated text*, not run-time behaviour.

### 1.3 Implementation language and constraints

**Python 3.10+, standard library only** `[AUTHOR]`, one package `sra8/`
with a launcher per tool in `bin/`. `make install` links the launchers
into `~/.local/bin` (or `PREFIX/bin`), so the tools run from anywhere and
still use this checkout.

A **C23 port** (standard library only) lives in `c/` with its own
Makefile and tests. It produces byte-identical objects, images, assembler listings,
maps, disassembly and messages, and is kept as an alternative, not as the
reference. Changes go to the Python tools first.

- One module, `sra8/isa.py`, is the **single source of truth** for opcodes,
  operand formats, condition codes, ALU codes and instruction bit layout.
  The assembler and the disassembler use it. Nothing else may
  hardcode an opcode number. `c/src/common/isa.c` mirrors it; the C tests
  check that both give the same `docs/isa.md` and VS Code grammar.
- Deterministic output: the same inputs always produce byte-identical files.
- Errors carry `file:line: message`. Warnings are printed but do not fail
  unless `-Werror`.

---

## 2. Target: the SRA-8 CPU

Source files, and what each defines (all in `../sra-8-fpga/sra-8-fpga/`):

| File | Defines |
|---|---|
| `CPU.v` | Top level: bus wiring, memory address mux, parameters (`BOOT_ADDR_BITS=12`, `INTPC_DEFAULT_VALUE=0`, `UART_DIV=104`). |
| `ControlUnit.v` | Microcode sequencer, control-word decode (the five MUXes), condition codes, interrupt entry/exit, boot sequence. |
| `InstructionRegister.v` | Instruction word bit fields. |
| `ALU.v` | The 12 ALU operations and flag rules. |
| `GeneralRegisters.v`, `GeneralRegister.v` | 16 × 8-bit registers. |
| `PC.v`, `INTPC.v` | The two 16-bit program counters. |
| `PSR.v` | Process state register (flags, IRQ mask, privilege level). |
| `INTR.v` | Interrupt request latch. |
| `MAR.v`, `PTBR.v`, `PTER.v` | Address translation registers. |
| `Memory.v` | 64 KiB single-port RAM. |
| `BootROM.v`, `BootCounter.v` | 4 KiB boot image copied to RAM at reset. |
| `Port.v`, `UartRx.v`, `UartTx.v` | The one I/O device: an 8N1 UART. |
| `UC.v`, `Clock.v` | Microstep counter and 4-phase clock. |
| `control_unit_gen/control_rom_gen.c` | **Microcode per opcode — the authoritative instruction semantics and opcode numbering.** |
| `control_unit_gen/fetch_rom_gen.c` | Microcode of the instruction fetch. |
| `fetch.mem`, `control_rom.mem` | Generated ROM images (identical to generator output). |
| `Instructions.xlsx` | Workbook: instruction list, control signals, microcode sketches, ALU codes. Mnemonics only, no encodings. |
| `asm/sra8asm.py`, `asm/sra8asm.c` | Legacy assembler (two identical implementations). The new assembly syntax is derived from it (Section 3); its output is the reference for the golden tests. |
| `echo.s`, `loader.s`, `terminal.s`, `user_echo.s`, `asm/example.s`, `asm/demo.s` | Sample programs. Golden tests for the new assembler. |
| `example.w` | An early language sketch. Not used by the kit. |
| `arduino_loader/*` | Temporary upload tooling for `loader.s` (2.12). Not targeted by the kit. |
| `f.l` | A legacy listing file (of `loader.s`), useful as encoding test vectors. |
| `icebreaker.pcf`, `Makefile` | Board: iCEBreaker (iCE40UP5K), 12 MHz clock, UART on the board's USB serial port. |

### 2.1 Overview

| Property | Value |
|---|---|
| Data width | 8 bit |
| Address width | 16 bit, byte addressed, 64 KiB address space |
| Instruction word | 32 bit, fixed size, stored **big-endian** (byte at lowest address = bits 31:24) |
| Data endianness | **Little-endian** for all 16/32-bit data laid out by software (`.dword`, `.addr`, page table entries, register pairs rN = low, rN+1 = high). The instruction word is the only big-endian object. |
| General registers | 16 × 8 bit, `r0`…`r15`; adjacent pairs form 16-bit address registers `rNa` = `rN` (low) : `rN+1` (high) |
| Program counters | `PC` (normal mode) and `INTPC` (interrupt mode), each 16 bit |
| Status | `PSR` 8 bit: flags Z N C V, IRQ mask, 2-bit privilege level |
| Hardware stack | **None.** No SP, no push/pop, no call/return instructions. `BRL` writes the return address into a register pair. |
| Addressing modes | Register-pair indirect or 16-bit absolute immediate. **No offset, no indexing, no auto-increment.** |
| ALU | 8-bit only. 12 operations. Shifts are by exactly one bit. No multiply, divide, or NOT. |
| Predication | Every instruction carries a 4-bit condition; when false the instruction is skipped. |
| Memory management | Optional one-level page table, 256-byte pages, active in privilege level ≠ 0 outside interrupt mode. |
| Interrupts | One external IRQ (UART receive), `SVC` instruction; single interrupt level, no nesting, no automatic state save. |
| I/O | One UART, 8N1, accessed by `PTR`/`PTW`. No memory-mapped I/O. |
| Clock | 12 MHz board clock; one microstep = 4 clocks; an instruction = 13…17 microsteps (see 2.11). |
| Physical RAM | 64 KiB (`Memory.v`: `spram[0:65535]`). `[VERIFY]` Comments in `loader.s` and the legacy assembler default (`--size 4096`) speak of 4096 bytes; that is the boot image size, not the RAM size. Confirm that the full 64 KiB is usable on the board. |

### 2.2 Registers

**General registers.** `r0`…`r15`, 8 bit each, all zero at reset. There are no
special-purpose general registers in hardware; conventions are software-only.
Any register may be a link register, pointer, etc.

**Register pairs.** An operand written `rNa` means the 16-bit value
`r(N+1):rN` (low byte in `rN`). The hardware forms the second register as
`(N + 1) mod 16` with a 4-bit adder, so `r15a` = `r0:r15` — legal but
almost certainly a bug in a program. Odd pairs (`r1a` = `r2:r1`) are legal.
The assembler warns on `r15a` (legacy behaviour; keep).

**PC / INTPC / XPC.** `PC` is the program counter of normal mode, `INTPC` that
of interrupt mode. Microcode addresses the "current" one as `XPC`; fetches,
branches and `BRL` use `XPC`, so the same code runs in either mode. The
instructions `PCW/PCR` and `INTPCW/INTPCR` access a specific one regardless of
mode, `XPCW/XPCR` the current one.

- After fetch, `XPC` already points at the **next** instruction (it is
  incremented once per fetched byte). `XPCR` and the link value of `BRL` are
  therefore "address of the following instruction".
- `[VERIFY]` `INTPC.v` reloads `INTPC` with `INTPC_DEFAULT_VALUE` (= 0) on
  every clock while the CPU is **not** in interrupt mode. Consequently every
  interrupt begins executing at physical address **0x0000**, and `INTPCW`
  executed in normal mode has no lasting effect. Comments in `echo.s`,
  `loader.s` and `asm/example.s` ("INTPC stops after intrw, so the next
  interrupt starts on this line") assume INTPC *persists*. Both models work
  with the convention in 2.8.3; the toolchain follows the RTL. Please confirm
  which behaviour is intended.

**PSR** (8 bit, zero at reset):

| Bit | Name | Meaning |
|---|---|---|
| 7:6 | `pl` | Privilege level. `0` = supervisor: no address translation. `1`,`2`,`3` = user: translation on (all three behave identically). |
| 5 | `irqm` | IRQ mask. `1` = IRQ **enabled** (the name is misleading; it is an enable). |
| 4 | — | Unused; reads back what was written. `[VERIFY]` reserved? |
| 3 | `Z` | Zero |
| 2 | `N` | Negative (bit 7 of result) |
| 1 | `C` | Carry / not-borrow / shifted-out bit |
| 0 | `V` | Signed overflow |

`PSRW` writes all 8 bits at once. There is **no privileged instruction**:
user-mode code can execute `PSRW`, `PTBRW`, `INTRW` etc. `[VERIFY]` intended?
The toolchain does not rely on protection either way.

**INTR** (read by `INTRR`, cleared by `INTRW`):

| Bit | Meaning |
|---|---|
| 4 | `irq` latched (UART byte received). Latches even when `irqm` = 0, so it can be polled. |
| 3 | `svc` latched |
| 2 | `pf` latched — never set by current hardware (no page faults) |
| 1 | `ini` latched — never set by current hardware |
| 0 | `int` — 1 while the CPU is in interrupt mode (live, not latched) |
| 7:5 | 0 |

`[VERIFY]` `INTR.v` sets `content[1]` from `pf_in` and `content[0]` from
`ini_in`, but outputs `ini_out = content[1]` and `pf_out = content[0]` —
swapped. Harmless today because neither source is ever driven.

`INTRW` ignores its operand value: any write clears all four latched bits.
Convention: `intrw #0`.

**PTBR** (16 bit), **MAR**, **PTER**: see 2.3. Only `PTBR` is software
visible (`PTBRW/PTBRR`).

### 2.3 Memory and address translation

Physical memory is a flat 64 KiB byte array. There is no I/O in the memory
map, no ROM in the map (the boot ROM is copied, see 2.9), and no memory
protection beyond translation.

**Page size** 256 bytes; the high address byte is the page number, the low
byte the offset.

**Translation is active** when `pl ≠ 0` **and** the CPU is not in interrupt
mode (`phys = (pl == 0) | is_interrupted` in `ControlUnit.v`). Fetches and
`LDR`/`STR` are translated; nothing else touches memory.

**Page table.** 256 entries × 2 bytes, little-endian, at physical address
`PTBR × 512`. Entry `n` (at `PTBR×512 + 2n`) maps virtual page `n`:

```
physical_address = (entry[7:0] << 8) | virtual_offset
```

Only the **low byte** of an entry is used (physical page number 0…255). The
high byte is ignored today (`PTER.v`: `pter_output = (pter_addr_out << 8) |
mar_byte0`, truncated to 16 bits). `[VERIFY]` reserved for a valid bit /
page fault later? There is no valid bit, so an unmapped page silently maps to
whatever the entry contains (0 → physical page 0). Only the low 7 bits of
`PTBR` matter (`PTBR << 9` truncated to 16 bits), i.e. the table must lie in
the first 64 KiB, at a 512-byte boundary.

The page table walk always happens (even in `pl 0`); its result is just not
used then. It costs no extra time — the microsteps are the same.

**Fetch constraint.** The fetch microcode reloads only the *low* MAR byte
between the four instruction bytes; therefore **an instruction must not cross
a 256-byte page boundary**. With 4-byte instructions this holds automatically
when code is 4-byte aligned. The toolchain must guarantee it (see 3.5, 5.2).

### 2.4 Instruction encoding

One 32-bit word, big-endian in memory (byte 0 = bits 31:24):

```
 31   28 27 26      20 19    16 15    12 11     8 7        0
┌───────┬──┬──────────┬────────┬────────┬────────┬──────────┐
│ cond  │0 │  opcode  │  arg1  │  arg2  │  arg3  │   imm0   │
└───────┴──┴──────────┴────────┴────────┴────────┴──────────┘
                                └──── imm16 = imm1:imm0 ────┘   (imm1 = bits 15:8, imm0 = bits 7:0)
```

- `cond` (4) — condition, see 2.5. `0` = always.
- bit 27 — unused, must be 0.
- `opcode` (7) — `opcode[6:1]` selects the instruction, `opcode[0]` = 1 for
  the **immediate form**. So register form = even, immediate form = odd.
- `arg1`, `arg2`, `arg3` (4 each) — register numbers.
- `imm0` (8) — 8-bit immediate. `imm16` occupies bits 15:0 and therefore
  **overlaps `arg2` and `arg3`**; an instruction with a 16-bit immediate has
  at most one register operand (`arg1`).

Note that within the big-endian word, `imm16` sits in bytes 2 (high) and 3
(low), i.e. it appears **big-endian in memory** although all data the program
handles is little-endian. Relocation code must get this right.

**Operand formats** (from `sra8asm.py`; `src` = register or immediate; an
immediate operand sets `opcode[0]`):

| Format | Operand syntax | arg1 | arg2 | arg3 | imm |
|---|---|---|---|---|---|
| `NONE` | — | | | | |
| `RD` | `rD` | rD | | | |
| `RDA` | `rDa` | rDa | | | |
| `SRC8` | `rS` / `#imm8` | rS | | | imm0 |
| `SRC16` | `rSa` / `#imm16` | rSa | | | imm16 |
| `RD_SRC8` | `rD, rS` / `rD, #imm8` | rD | rS | | imm0 |
| `RD_SRC16` | `rD, rSa` / `rD, #imm16` | rD | rSa | | imm16 |
| `RDA_SRC16` | `rDa, rSa` / `rDa, #imm16` | rDa | rSa | | imm16 |
| `ALU3` | `rD, rN, rM` / `rD, rN, #imm8` | rD | rN | rM | imm0 |

Register operands always fill `arg1, arg2, arg3` in the order written.
Unused fields are 0.

**Undefined opcodes** (odd opcodes of instructions without an immediate form:
7, 11, 15, 19, 23, 27, 109, 111, 113; and 114…127) have all-zero microcode
and never reset the microstep counter. The sequencer then runs into
neighbouring opcodes' microcode: **behaviour is undefined and destructive**.
The assembler must never emit them; the disassembler shows them as raw data.

### 2.5 Condition codes

`cond` field value → suffix → true when:

| # | Suffix | Condition | # | Suffix | Condition |
|---|---|---|---|---|---|
| 0 | `al` | always | 8 | `nvr` | never (instruction becomes a 1-microstep no-op) |
| 1 | `eq` | Z | 9 | `ne` | ¬Z |
| 2 | `mi` | N | 10 | `pl` | ¬N |
| 3 | `vs` | V | 11 | `vc` | ¬V |
| 4 | `su` | ¬C (unsigned <, "borrow") | 12 | `geu` | C (unsigned ≥) |
| 5 | `gu` | C ∧ ¬Z (unsigned >) | 13 | `seu` | ¬C ∨ Z (unsigned ≤) |
| 6 | `ss` | N ⊕ V (signed <) | 14 | `ges` | ¬(N ⊕ V) (signed ≥) |
| 7 | `gs` | ¬(N ⊕ V) ∧ ¬Z (signed >) | 15 | `ses` | (N ⊕ V) ∨ Z (signed ≤) |

Written as a suffix after a dot: `add.eq r1, r2, r3`, `br.su =loop`. Without a
suffix the condition is `al`. Any instruction can be predicated, including
`svc`, `ptw`, `str`. A false condition costs one microstep and changes
nothing (flags included).

The unsigned conditions are meaningful after `CMP`/`SUBS` (C = no borrow):
`su` = a < b, `geu` = a ≥ b, `gu` = a > b, `seu` = a ≤ b.

### 2.6 ALU operations and flags

ALU code (4 bit, from `ALU.v` / "ALU operations" sheet) and result, with
`a` = first operand (`alu_op1`), `b` = second (`alu_op2`), `C` = PSR carry in:

| Code | Op | Result | Z | N | C | V |
|---|---|---|---|---|---|---|
| 0 | ADD | a + b | r=0 | r7 | carry out (bit 8) | signed overflow |
| 1 | ADDC | a + b + C | r=0 | r7 | carry out | signed overflow |
| 2 | SUB | a − b | r=0 | r7 | **¬borrow** (1 if a ≥ b unsigned) | signed overflow |
| 3 | SUBC | a − b − 1 + C  (= a − b − borrow) | r=0 | r7 | ¬borrow | signed overflow |
| 4 | AND | a ∧ b | r=0 | r7 | **0** | 0 |
| 5 | OR | a ∨ b | r=0 | r7 | **0** | 0 |
| 6 | EOR | a ⊕ b | r=0 | r7 | **0** | 0 |
| 7 | LSL | a << 1 | r=0 | r7 | old a7 | 0 |
| 8 | LSR | a >> 1 (logical) | r=0 | r7 | old a0 | 0 |
| 9 | ASR | a >> 1 (sign-extending) | r=0 | r7 | old a0 | 0 |
| 10 | CSL | {a[6:0], C} (rotate left through carry) | r=0 | r7 | old a7 | 0 |
| 11 | CSR | {C, a[7:1]} (rotate right through carry) | r=0 | r7 | old a0 | 0 |

Notes the toolchain must respect:

- Flags are written **only** by the `S` variants and the flags-only
  instructions (`CMP` …). Plain `ADD`, `MOV`, `LDR`, branches etc. never touch
  flags. This makes flags live across long sequences and is exploited by
  the sample programs (`subs lo; sub.su hi, hi, #1`, written before `SUBC`
  was repaired).
- Logical operations **clear C and V**. Shifts clear V.
- **SUBC is the conventional subtract-with-borrow** `[AUTHOR]`: `ALU.v`
  computes `a + ¬b + C` = `a − b − 1 + C`, and C out is ¬borrow. It was
  repaired in the RTL (the first version of this document described the
  earlier, faulty `a − b + C`). Multi-byte subtraction is therefore
  `subs` on the low byte followed by `subc` on the higher bytes, and a
  multi-byte comparison is `cmp` followed by `subcd`.
- The ALU is 8 bit; 16-bit arithmetic is two instructions (`adds` + `addc`).
- Shift amount is always 1. Shifting by `n` is `n` instructions or a loop.
- There is no NOT instruction. Use `eor rD, rS, #0xFF`. Negation is
  `eor rD, rS, #0xFF` followed by `add rD, rD, #1`. The mnemonics `MOVS`,
  `MVN` and `MVNS` of earlier workbook versions **have been removed from
  the instruction set** `[AUTHOR]`; they have no opcode and the assembler
  does not know them.

### 2.7 Instruction set

Opcode numbers are **binding** (from `control_rom_gen.c`). `R` = register
form opcode, `I` = immediate form. "Steps" = microsteps of the instruction
body excluding fetch and including the final reset step (for timing, 2.11).

#### Register and system register moves

| Mnemonic | Operands | Format | R | I | Steps | Semantics |
|---|---|---|---|---|---|---|
| `mov` | `rD, rS/#imm8` | RD_SRC8 | 0 | 1 | 2 | rD ← src |
| `mova` | `rDa, rSa/#imm16` | RDA_SRC16 | 2 | 3 | 3 | rD ← lo(src); rD+1 ← hi(src) |
| `pcw` | `rSa/#imm16` | SRC16 | 4 | 5 | 3 | PC ← src. Normal mode: a jump. Interrupt mode: sets the return address. |
| `pcr` | `rDa` | RDA | 6 | — | 3 | rDa ← PC |
| `xpcw` | `rSa/#imm16` | SRC16 | 8 | 9 | 3 | current PC ← src (a jump in either mode; same as `br`) |
| `xpcr` | `rDa` | RDA | 10 | — | 3 | rDa ← current PC (= address of next instruction) |
| `intpcw` | `rSa/#imm16` | SRC16 | 12 | 13 | 3 | INTPC ← src. Interrupt mode: a jump. Normal mode: no lasting effect `[VERIFY]` (2.2) |
| `intpcr` | `rDa` | RDA | 14 | — | 3 | rDa ← INTPC |
| `psrw` | `rS/#imm8` | SRC8 | 16 | 17 | 2 | PSR ← src (pl, irqm, flags all at once) |
| `psrr` | `rD` | RD | 18 | — | 2 | rD ← PSR |
| `ptbrw` | `rSa/#imm16` | SRC16 | 20 | 21 | 3 | PTBR ← src |
| `ptbrr` | `rDa` | RDA | 22 | — | 3 | rDa ← PTBR |
| `intrw` | `rS/#imm8` | SRC8 | 24 | 25 | 2 | INTR ← 0 (value ignored). Leaves interrupt mode if nothing is pending afterwards. |
| `intrr` | `rD` | RD | 26 | — | 2 | rD ← INTR (bit layout in 2.2) |

#### Memory

| Mnemonic | Operands | Format | R | I | Steps | Semantics |
|---|---|---|---|---|---|---|
| `ldr` | `rD, rSa/#imm16` | RD_SRC16 | 28 | 29 | 6 | rD ← mem[xlat(addr)] |
| `str` | `rS, rDa/#imm16` | RD_SRC16 | 30 | 31 | 6 | mem[xlat(addr)] ← rS. **Source register first**, address second. |

#### Arithmetic and logic, three operands: `rD ← rN op (rM | imm8)`

| Mnemonic | R | I | Mnemonic (sets flags) | R | I | Steps | ALU |
|---|---|---|---|---|---|---|---|
| `add` | 32 | 33 | `adds` | 34 | 35 | 4 | ADD |
| `addc` | 36 | 37 | `addcs` | 38 | 39 | 4 | ADDC |
| `sub` | 40 | 41 | `subs` | 42 | 43 | 4 | SUB |
| `subc` | 44 | 45 | `subcs` | 46 | 47 | 4 | SUBC |
| `and` | 48 | 49 | `ands` | 50 | 51 | 4 | AND |
| `or` | 52 | 53 | `ors` | 54 | 55 | 4 | OR |
| `eor` | 56 | 57 | `eors` | 58 | 59 | 4 | EOR |

Format `ALU3`. The immediate replaces `rM` (the second ALU operand), so
`sub r1, r2, #5` is r2 − 5; there is no reverse-subtract.

#### Shifts, two operands: `rD ← op(rS | imm8)` (by one bit)

| Mnemonic | R | I | Sets flags | R | I | Steps | ALU |
|---|---|---|---|---|---|---|---|
| `lsl` | 60 | 61 | `lsls` | 62 | 63 | 3 | LSL |
| `lsr` | 64 | 65 | `lsrs` | 66 | 67 | 3 | LSR |
| `asr` | 68 | 69 | `asrs` | 70 | 71 | 3 | ASR |
| `csl` | 72 | 73 | `csls` | 74 | 75 | 3 | CSL |
| `csr` | 76 | 77 | `csrs` | 78 | 79 | 3 | CSR |

Format `RD_SRC8`. The immediate form shifts the *immediate* and puts the
result in `rD` (rarely useful; legal).

#### Flags only (result discarded)

| Mnemonic | Operands | Format | R | I | Steps | ALU | Meaning |
|---|---|---|---|---|---|---|---|
| `cmn` | `rN, rM/#imm8` | RD_SRC8 | 80 | 81 | 4 | ADD | compare negative |
| `addcd` | `rN, rM/#imm8` | RD_SRC8 | 82 | 83 | 4 | ADDC | |
| `cmp` | `rN, rM/#imm8` | RD_SRC8 | 84 | 85 | 4 | SUB | compare: flags of rN − rM |
| `subcd` | `rN, rM/#imm8` | RD_SRC8 | 86 | 87 | 4 | SUBC | |
| `andd` | `rN, rM/#imm8` | RD_SRC8 | 88 | 89 | 4 | AND | bit test |
| `ord` | `rN, rM/#imm8` | RD_SRC8 | 90 | 91 | 4 | OR | |
| `eord` | `rN, rM/#imm8` | RD_SRC8 | 92 | 93 | 4 | EOR | |
| `lsld` | `rN/#imm8` | SRC8 | 94 | 95 | 3 | LSL | |
| `lsrd` | `rN/#imm8` | SRC8 | 96 | 97 | 3 | LSR | |
| `asrd` | `rN/#imm8` | SRC8 | 98 | 99 | 3 | ASR | |
| `csld` | `rN/#imm8` | SRC8 | 100 | 101 | 3 | CSL | |
| `csrd` | `rN/#imm8` | SRC8 | 102 | 103 | 3 | CSR | |

For these, `rN` is in `arg1` and `rM` in `arg2` (unlike the 3-operand forms).

#### Control flow

| Mnemonic | Operands | Format | R | I | Steps | Semantics |
|---|---|---|---|---|---|---|
| `br` | `rTa/#imm16` | SRC16 | 104 | 105 | 3 | current PC ← target (absolute) |
| `brl` | `rLa, rTa/#imm16` | RDA_SRC16 | 106 | 107 | 5 | rLa ← address of next instruction; current PC ← target |

There are no relative branches: every branch target is a 16-bit absolute
address, hence every branch needs a relocation. Return from a subroutine is
`br rLa`.

#### I/O and other

| Mnemonic | Operands | Format | R | I | Steps | Semantics |
|---|---|---|---|---|---|---|
| `ptr` | `rD` | RD | 108 | — | 2 | rD ← last received UART byte; **clears the port IRQ line** (not the INTR latch) |
| `ptw` | `rS` | RD | 110 | — | 2 | start transmitting rS. **No busy flag**: a second `ptw` within one byte time (10 bit periods) is silently dropped by `UartTx`. |
| `svc` | — | NONE | 112 | — | 2 | raise supervisor call → interrupt mode before the next instruction |

There is **no `nop`, `halt`, `ret`, `push`, `pop`, `call`, `jmp`**, and the
assembler has no pseudo-instructions either. The idioms are: no-op
`mov.nvr r0, r0`; call `brl rLa, =target`; return `br rLa`; stop
`.l spin:  br .b =spin`.

#### Encoding test vectors (from `f.l`, linked at 0)

| Source | Bytes |
|---|---|
| `intpcw =enter_program` (0x00A4) | `00 D0 00 A4` |
| `mova r2a, =msg_banner` (0x0100) | `00 32 01 00` |
| `brl r12a, =puts` (0x00E4) | `06 BC 00 E4` |
| `br.ne .b =wait_mark` (0x0010) | `96 90 00 10` |
| `add.ne r9, r9, #1` | `92 19 90 01` |
| `ors r1, r6, r7` | `03 61 67 00` |
| `str r0, r2a` | `01 E0 20 00` |
| `ldr r0, r2a` | `01 C0 20 00` |
| `br r10a` | `06 8A 00 00` |
| `svc` | `07 00 00 00` |
| `cmp r0, #0xA5` | `05 50 00 A5` |
| `ptr r0` / `ptw r0` | `06 C0 00 00` / `06 E0 00 00` |
| `intrr r1` | `01 A1 00 00` |
| `psrw #0x40` | `01 10 00 40` |
| `sub.su r7, r7, #1` | `42 97 70 01` |
| `andd r1, #0x10` | `05 91 00 10` |

### 2.8 Interrupts, SVC and privilege

#### 2.8.1 Sources

| Source | Raised by | Latched in INTR bit | Cleared by |
|---|---|---|---|
| IRQ | UART receiver: a complete byte arrived. The port keeps its `irq` line high until `ptr`. | 4 | `ptr` drops the line; `intrw` clears the latch. Doing `intrw` **without** `ptr` re-latches immediately. |
| SVC | `svc` instruction | 3 | `intrw` |
| PF, INI | never (unwired) | 2, 1 | `intrw` |

INTR latches IRQ **regardless of `irqm`**, which is how the polling samples
work (`intrr` → test bit 4 → `ptr` → `intrw #0`).

#### 2.8.2 Entry and exit

Entry happens when the CPU is in normal mode and (`svc`, `pf` or `ini` is
latched) or (`irq` latched **and** `irqm` = 1 **and** the sequencer is at
microstep 0, i.e. between instructions). Then:

- `is_interrupted` ← 1. The current program counter becomes `INTPC`.
- `INTPC` holds `INTPC_DEFAULT_VALUE` = **0x0000** (see the `[VERIFY]` in 2.2).
- Address translation is **off** (physical addresses), whatever `pl` says.
- `PC` is frozen and points at the instruction the interrupted code would
  have executed next (after `svc`: the instruction following it).
- **Nothing is saved.** General registers, PSR flags, and `pl` are shared
  with the interrupted code. The handler must save what it clobbers,
  including the flags (`psrr`/`psrw`) if the interrupted code may depend
  on them.
- No nesting: while interrupted, further IRQs stay latched and are taken
  after exit (if still pending).

Exit happens on the first microstep-0 at which nothing is pending
(`svc`, `pf`, `ini` all clear **and** not (`irq` ∧ `irqm`)) while
interrupted. Practically: the instruction after `intrw #0` in the handler is
**not** executed; the CPU resumes at `PC` in normal mode with the current
`pl` and translation state. If `irqm` = 0 and only `irq` is latched, the CPU
also exits (mask is honoured at exit too).

#### 2.8.3 The vector convention

Because reset and interrupt both start at physical **0x0000**, the first
instruction of every image is

```
        intpcw =__isr           ; in interrupt mode: jump to the handler
                                ; in normal mode: harmless
```

followed by the normal start-up code. A program that never enables
interrupts and never executes `svc` may still keep it (costs 3 microsteps
once). The handler ends with `intrw #0`.

Distinguishing reset from interrupt is also possible with `intrr` bit 0.

#### 2.8.4 Privilege level and the mode switch idiom

`pl` lives in PSR and is only meaningful outside interrupt mode. Switching
a program into user mode is done from interrupt mode, as `loader.s` does:

```
enter_program:                  ; reached via svc, so translation is off
        ptbrw #TABLE_PTBR       ; page table
        pcw   #0x0000           ; where the user program starts (virtual)
        psrw  #0x40             ; pl = 1, irqm = 0, flags = 0
        intrw #0                ; leave interrupt mode → fetch at PC, translated
```

A user program's `svc` lands at physical 0 again with translation off — the
supervisor's `__isr` sees `intrr` bit 3 set and `psrr` bits 7:6 ≠ 0.

### 2.9 Reset and boot

After configuration or the reset button (`BTN2`), in order:

1. Stabilisation: the control unit idles 2²² clocks (≈ 0.35 s at 12 MHz).
   `LED5` is on.
2. Boot copy: 4096 bytes of the boot ROM (`program.mem`, `BOOT_ADDR_BITS`
   = 12) are copied to RAM addresses **0x0000…0x0FFF**, one byte per
   microstep.
3. Execution starts at **PC = 0x0000** in normal mode with **PSR = 0**
   (`pl 0`, IRQ disabled, flags clear), all registers 0, INTR 0.

Consequences for the toolchain:

- A bootable image is **at most 4096 bytes** and is placed at 0. Bytes beyond
  the image's end inside the 4 KiB are whatever the `.mem` file contains (the
  legacy assembler pads with 0).
- RAM above 0x0FFF is **uninitialised** (SPRAM power-up content). `.bss`
  must be zeroed by the program's start-up code; nothing may assume zero
  memory.
- Anything larger has to be loaded at run time by a program in the boot
  image. Only a temporary loader exists today (2.12).

### 2.10 The UART port

- 8N1. Baud divisor `UART_DIV = 104` → 12 MHz / 104 = **115 384 baud
  (≈ 115200)**, set by the RTL commit "USB serial port". One byte on the
  wire (10 bits) takes 86.7 µs = 1040 clocks ≈ 18 instructions. Older
  comments in the sample programs and the Arduino sketch still speak of
  9600 baud (`DIV = 1250`); they are outdated.
- Receive: one-byte holding register, **no FIFO**. A byte that arrives before
  the previous one was read by `ptr` replaces it. `ptr` returns the last
  complete byte and clears the IRQ line.
- Transmit: `ptw` starts sending immediately if idle, otherwise the byte is
  **lost**. There is no busy/ready flag; software must wait at least 10 bit
  times (1040 clocks) between writes. A delay loop should derive its count
  from one named constant so that a change of the divisor is a one-line
  edit.
- Board pins: `RX` = pin 6, `TX` = pin 9 (the iCEBreaker's USB serial
  port), 3.3 V.

### 2.11 Timing

- One microstep = 4 clocks (`Clock.v` phases 0…3; control word loaded at
  phase 0, registers written at phase 2, step counter advances at phase 3).
- Fetch = 11 microsteps, always.
- Instruction body = "Steps" column in 2.7 (the last one is the reset step).
- Skipped instruction (false condition) = 1 microstep.

```
cycles(instr) = 4 × (11 + steps)              e.g. mov 52, add 60, ldr/str 68, brl 64
cycles(skipped) = 4 × 12 = 48
```

At 12 MHz: ≈ 200 000 instructions/s. The kit uses this model only to
compute delay-loop constants (UART pacing).

### 2.12 The temporary loader (`loader.s`, `arduino_loader/`)

`loader.s` with the Arduino sketch was **a temporary tool, and its protocol
is not final** `[AUTHOR]`. The kit does not target it: there is no linker
script for uploaded programs, no `program.h` output format, no uploader.
`loader.s` and `user_echo.s` are still used as assembler test inputs
(Section 8), because they exercise `svc`, `ptbrw` and the privilege
switch of 2.8.4.

For orientation only, what the temporary loader does: it receives `0xA5`,
a 16-bit length (low byte first) and the program bytes over the UART,
stores the program at physical `0x0400`, builds a page table at `0x0200`
that maps it to virtual address 0, answers with the 8-bit sum of the
bytes, and starts the program in `pl 1`.

### 2.13 Hazards the toolchain must know (summary)

1. Instructions must not cross a page boundary → keep code 4-aligned.
2. Undefined opcodes are destructive → never emit; assembler rejects.
3. There is no stack and no offset addressing → every stack access is a
   computed address.
4. Logical ops clear C → do not interleave `ands`/`ors` between `subs` and a
   dependent `subc` or `.su`.
5. `ptw` without pacing loses bytes; `ptr`-less `intrw` re-enters the handler.
6. Interrupt handlers share registers and flags with the interrupted code.
7. Bootable image ≤ 4096 bytes; RAM beyond is garbage until written.
8. `r15a` wraps to `r0`.
9. `str` operand order is *source, address*; `ldr` is *dest, address*.
10. `imm16` is stored big-endian inside the instruction; data is little-endian.

---

## 3. Assembly language (`sra8-as`)

The syntax is the legacy `sra8asm.py` syntax, **minus** absolute placement
(`.org`, `.align`), **plus** named sections and explicit import/export for
linking. It is deliberately small. `[AUTHOR]`

### 3.1 Lexical

- Case-insensitive mnemonics, registers and condition suffixes; labels and
  symbols are case-sensitive. `[DECISION: default = as stated]`
- Comment: `;` to end of line. **This is the only comment syntax.** `[AUTHOR]`
- Numbers: `123`, `0d123`, `0x7B`, `0o173`, `0b1111011`, `'a'` (with escapes
  `\n \t \r \0 \\ \' \"`), optional leading `-`/`+`.
- Registers: `r0`…`r15`; pairs `r0a`…`r15a`. `r15a` draws a warning (2.2).
- Immediates are prefixed with `#`: `#10`, `#0x1F`, `#'a'`, `#-1`.
- Symbol references are prefixed with `=`: `=label`.
- Identifiers: `[A-Za-z_][A-Za-z0-9_.]*` (a dot is allowed inside a name,
  e.g. for generated `function.label` symbols). Names starting
  with `__` are reserved for the toolchain.

### 3.2 Statements

```
[label:]* [.l local:]* [mnemonic[.cond] operands | .directive args]  [; comment]
```

Several labels may precede a statement. Operands are comma-separated.
Only real instructions of Section 2.7 exist: there are **no
pseudo-instructions** (`nop`, `ret`, `call`, `halt`, … do not exist). `[AUTHOR]`

### 3.3 Labels, import and export

- `name:` — label in the current section. Visible in the whole file, and
  only in this file unless exported.
- `.l name:` — **local label**, may be defined many times. Referenced as
  `.b =name` (nearest definition before this line) or `.f =name` (nearest
  after). Local labels never appear in the object file.
- `.export name[, name…]` — make labels defined in this file visible to
  other objects. Exporting an undefined name is an error.
- `.import name[, name…]` — declare symbols defined in another object.

Rules `[AUTHOR]`:

- `.import` and `.export` are the **only** linkage directives. There is no
  `.global`, `.globl`, `.extern`.
- **No implicit import.** A reference to a name that is neither defined in
  the file nor imported is an error in the assembler.
- **No weak symbols.** A name exported by two objects is a link error.
- **No constant symbols.** There is no `.equ` / `.set`; named constants are
  done with the preprocessor (`!DEFINE`, 3.7).
- Importing a name that the file also defines is an error. An import that is
  never used draws a warning.

### 3.4 Operands

| Operand | Meaning |
|---|---|
| `rN` | 8-bit register |
| `rNa` | 16-bit register pair |
| `#number` | immediate constant (8 or 16 bit, by instruction format) |
| `=label` | address of a label (only where a 16-bit immediate is allowed) |
| `=label + const`, `=label - const` | address plus/minus a constant |
| `.b =label`, `.f =label` | nearest local label before / after; `± const` allowed as well |

That is the complete list `[AUTHOR]`. There are **no other expressions**: no
arithmetic between constants (`#1+2`), no `label − label`, no parentheses,
**no current-address operator**, **no `lo()` / `hi()`** byte-selection
operators. `const` is a number as in 3.1; whitespace around `+`/`-` is
optional.

Consequence: an address can only be materialised as a whole 16-bit value
(`mova rNa, =label`, or the `imm16` form of `ldr`/`str`/`br`/`brl`/…); its
bytes are then available as `rN` (low) and `rN+1` (high).

### 3.5 Sections

Exactly three section types exist, each with an optional name `[AUTHOR]`:

| Directive | Content allowed |
|---|---|
| `.code [name]` | instructions and data directives |
| `.data [name]` | data directives only (an instruction here is an error) |
| `.bss [name]` | `.res` only; occupies no bytes in the object or the image |

- A section is identified by **type and name**. `.code` without a name is
  the *unnamed* code section; `.code vector` is the code section `vector`.
  `.code foo` and `.data foo` are different sections.
- Re-opening a section (same type and name) later in the file continues it.
- Sections with the same type and name from different objects are
  concatenated by the linker in command-line order.
- Before the first section directive, the current section is the unnamed
  `.code` section (legacy behaviour).
- No other section types, no `.section`, no flags.
- **`.org` and `.align` do not exist.** `[AUTHOR]` Placement and alignment
  are the linker's job (5.2). The assembler reports them as errors with the
  hint "placement is done by the linker script".

**Instruction alignment.** The linker places every code section at an
address that is a multiple of 4. Inside a code section every instruction
must start at an offset that is a multiple of 4; otherwise the assembler
reports an error ("instruction at unaligned offset; pad the preceding data
to a multiple of 4 bytes or move it to a `.data` section"). Together these
guarantee that no instruction crosses a page boundary (2.3).
`[DECISION: default = error, no automatic padding]`

### 3.6 Data directives

The legacy set, unchanged:

| Directive | Size | Notes |
|---|---|---|
| `.byte v, …` / `.word v, …` | 1 | legacy: `.word` **is 8 bit** on this CPU. Both names stay. |
| `.dword v, …` | 2 | little-endian, numbers only |
| `.qword v, …` | 4 | little-endian, numbers only |
| `.addr v, …` | 2 | little-endian; the only data directive that accepts `=label [± const]` |
| `.ascii "s"` / `.asciz "s"` | n / n+1 | Latin-1 bytes; escapes as in 3.1 |
| `.res n` | n | reserved space: nothing in `.bss`, zero bytes in `.code` / `.data` |

In directive arguments the `#` before a number is optional (legacy).
8-bit values accept −128…255, 16-bit −32768…65535, 32-bit
−2³¹…2³²−1 (legacy `fit()` rule). There is no `.incbin`, `.fill`, `.space`.
`[AUTHOR: no .incbin]`

### 3.7 Preprocessor (legacy, text level, unchanged)

| Directive | Meaning |
|---|---|
| `!INCLUDE path` | paste file (relative to the including file) |
| `!DEFINE name text` | alias; `!name` anywhere outside quotes is replaced by `text`, recursively (depth ≤ 32) |

**No new preprocessor directives** `[AUTHOR]`: no conditionals, no
command-line defines, no include search path.

### 3.8 Command line

```
sra8-as [-o out.o] [-l out.lst] [-Werror] file.s
```

One source file in, one object out (default name: source name with `.o`).
There is **no `--image` mode** `[AUTHOR]`: the assembler never writes a
memory image; that is always the linker's job.

### 3.9 Listing format

```
<type>[:<name>]+<offset>  <bytes up to 8>   <source line>
```

e.g. `code+0010  06 BA 00 00  brl r10a, =getc`, followed by the sections,
all labels with an exported mark, the imports and the relocations. Fields
that a relocation will fill show the index or addend. The listing is made
from the assembler's own state, because the object keeps neither source
lines nor labels that are not exported; it is the only place where those
labels can be seen.

### 3.10 Porting legacy programs; features that do not exist

The six sample programs need exactly one change to assemble: delete the
line `.org #0x0000` (the linker script places the code at 0). The copies in
`examples/asm/` are ported that way and are otherwise untouched.

For reference, everything a reader might expect but that was deliberately
left out: `.org`, `.align`, `.global`/`.extern`, `.weak`, `.equ`/`.set`,
`.section`, `.incbin`, `.fill`, pseudo-instructions, expressions other
than `label ± const`, `lo()`/`hi()`, the current-address operator `.`,
`//` and `/* */` comments, conditional assembly, `--image`.

---

## 4. Object file format

A **JSON** text file, extension `.o`, version 2. `[AUTHOR: JSON; only
header, sections, exports and relocations]`

```json
{
  "format": "sra8-obj",
  "version": 2,
  "source": "main.s",
  "sections": [
    {"section": "code", "size": 96, "data": "00D000A4..."},
    {"section": "code:vector", "size": 4, "data": "00D00000"},
    {"section": "data", "size": 12, "data": "0D0A5352..."},
    {"section": "bss", "size": 81}
  ],
  "exports": [
    {"name": "puts", "section": "code", "offset": 84}
  ],
  "relocations": [
    {"section": "code:vector", "offset": 0, "type": "IMM16", "import": "__isr", "addend": 0},
    {"section": "code", "offset": 12, "type": "IMM16", "from": "bss", "index": 2},
    {"section": "data", "offset": 4, "type": "ABS16", "from": "code", "index": 84}
  ]
}
```

- **Header**: `format`, `version`, `source` (the source file name).
- **Sections** are identified everywhere by their label: the type, then
  `:name` for a named section. `data` is uppercase hex, exactly `size`
  bytes; bss sections have none.
- **Exports**: the exported labels with section label and offset. Labels
  that are not exported, local `.l` labels and source lines are not in
  the object. `[AUTHOR]`
- **Relocations**: the place to patch (`section`, `offset`), the `type`,
  and where the address comes from `[AUTHOR]`:
  - `from` a section of this object at `index` — for every reference to a
    label of the same file; the index is the label's offset plus the
    constant of `=label ± n` and may lie outside the section;
  - or an `import`ed name and an `addend`, looked up by the linker among
    the exports of all objects and the script symbols.

  The imported names of an object are exactly the `import` names of its
  relocations; there is no separate list.

**Relocation types** — two, because an address can only be used as a
whole (3.4). The value written is computed modulo 2¹⁶:

| Type | Produced by | Patches |
|---|---|---|
| `IMM16` | `=label` in an instruction | the instruction at `offset` (4 bytes): byte `offset+2` ← high byte, byte `offset+3` ← low byte (big-endian inside the instruction word, 2.4) |
| `ABS16` | `.addr =label` | 2 data bytes at `offset`, little-endian |

The type cannot be derived from the section: an `.addr` in a code section
is `ABS16`. Before linking, the patched field holds the index or the
addend.

---

## 5. Linker (`sra8-ld`) and linker script

### 5.1 Command line

```
sra8-ld [-T script.ld] [-o out.bin] [--format bin|mem|ihex] [--mem-size N]
        [-M out.map] objects...
```

- Without `-T` the built-in script `boot.ld` (5.5) is used.
- All objects on the command line are linked, in that order. There are no
  libraries and no search paths.
- Exit status ≠ 0 on: an import that no object and no script symbol
  provides, a name exported twice, a section that the script does not
  place, a region overflow, overlapping regions.

### 5.2 Linker script language

A small, line-oriented language with only what this machine needs
`[AUTHOR: simple and clean]`. One statement per line, `;` starts a comment
(as in assembly), keywords are lower case, numbers are decimal, `0x…` or
`0b…`. The whole language:

```
; boot.ld — a program in the boot ROM, privilege level 0

memory boot  start 0x0000  size 0x1000     ; copied from the boot ROM at reset
memory ram   start 0x1000  size 0xF000     ; uninitialised RAM

place boot
    code vector                            ; the first instruction: address 0
    code *                                 ; every code section not placed yet
    data *
end

place ram
    symbol __bss_start                     ; = current address
    bss *
    symbol __bss_end
end

symbol __stack_top = last ram              ; 0xFFFF
```

Grammar:

```
script  := { memory | place | symbol }
memory  := "memory" NAME "start" NUMBER "size" NUMBER
place   := "place" REGION  { item }  "end"
item    := TYPE [ NAME | "*" ]             ; TYPE = "code" | "data" | "bss"
         | "align" NUMBER
         | "symbol" NAME
symbol  := "symbol" NAME "=" ( NUMBER | "start" REGION | "last" REGION )
```

Semantics:

| Statement | Meaning |
|---|---|
| `memory N start A size S` | Declares an address range. Ranges must not overlap and must lie within 0…0xFFFF. |
| `place N … end` | Fills region `N` from its start, in the order of the items. A region may have only one `place` block. |
| `code` / `data` / `bss` | Places the **unnamed** section of that type (all objects' contributions, in command-line order). |
| `code NAME` | Places the section of that type with that name. It is not an error if no object has it. |
| `code *` | Places every section of that type that has not been placed yet: unnamed first, then named ones in order of first appearance on the command line. |
| `align N` | Advances the current address to a multiple of `N` (gap is zero-filled). |
| `symbol NAME` (inside `place`) | Defines `NAME` = current address. |
| `symbol NAME = …` (top level) | Defines `NAME` = a number, the first address of a region (`start`), or its last address (`last`). |

- Script symbols behave like exported labels: objects use them via
  `.import`. A script symbol with the same name as an exported label is an
  error.
- **Code sections are always placed at a multiple of 4** (automatic, no
  `align` needed); data and bss sections have no alignment.
- A section is placed exactly once; the first item that matches it wins.
  **Every section of every object must be placed**, otherwise the link
  fails naming the section and the object (there is no orphan placement).
- Overflowing a region is an error that names the section that did not fit.

There is nothing else: no expressions, no assertions, no separate load
address, no discard, no include.

### 5.3 Link algorithm

1. Read all objects. Collect exports; duplicate name = error.
2. Run the script: assign an address to every section contribution, define
   script symbols, check regions.
3. Resolve every import and every file-internal label reference.
4. Apply relocations.
5. Check that every code section starts at a multiple of 4 (guaranteed by
   step 2; asserted anyway).
6. Write the outputs.

### 5.4 Output formats

The **image** consists of all `code` and `data` bytes. It starts at the
start address of the lowest region that contains code or data and ends at
the last code/data byte; gaps are zero-filled. `bss` contributes nothing
(a `bss` section placed *between* loaded sections becomes a zero-filled
gap).

| `--format` | Extension | Content |
|---|---|---|
| `bin` (default) | `.bin` | The image as raw bytes. |
| `mem` | `.mem` | Verilog `$readmemh` file: line `@0000`, then `--mem-size` bytes (default 4096) as `XX XX XX XX` per line, uppercase hex, zero-padded. Exactly the legacy format, so it replaces `program.mem` of the FPGA build. Requires the image to start at address 0 and to fit into `--mem-size`. |
| `ihex` | `.hex` | Intel HEX, 16-byte records. `[DECISION: default = yes, cheap]` |

`-M` writes the **map**: regions with used/free bytes, every section
contribution with address, size and object, then the exported labels and
script symbols sorted by address. There is no linked listing: the objects
carry no source lines.

### 5.5 Built-in scripts (`ldscripts/`)

| Script | Use | Layout |
|---|---|---|
| `boot.ld` | A program in the boot ROM, `pl 0`, owning the whole machine. **Default.** | The example in 5.2: code and data in the 4 KiB boot region from address 0, bss above it, stack from the top of RAM downward. `[VERIFY]` assumes the full 64 KiB RAM is usable (2.1). |
| `flat.ld` | Reproduces the legacy assembler's layout; used by the golden tests. | One region `0x0000` size `0x10000`; `code *`, `data *`, `bss *`. |

---

## 6. `sra8-objdump`

```
sra8-objdump [-d] [-s] [-t] [-r] [--start ADDR] [--end ADDR] file.o | file.bin | file.mem
```

- `-d` disassemble (the default when no option is given). Objects: every
  section, with `.import` / `.export`, the exported labels, imports shown
  inline as `=name±addend`, and generated labels `L<section>_<offset>` for
  section targets (the original names are not in the object). Images: from `--start` (default 0), addresses as `#0x…`
  immediates. Output uses only the syntax of Section 3, with addresses and
  bytes in `;` comments, so it assembles again to the same bytes.
- `-s` hex dump, `-t` sections, exports and imports, `-r` relocations.
- A word that is not exactly what the assembler would produce (undefined
  opcode, bit 27 set, a non-zero unused field) is written as
  `.byte` with four values, so that the round trip stays byte-exact.

---

## 7. Building a program

There is no driver; the example `Makefile` in `examples/` shows the steps:

```
sra8-as -o build/terminal.o  examples/asm/terminal.s
sra8-ld -T ldscripts/flat.ld --format mem -o program.mem -M build/terminal.map \
        build/terminal.o
```

A program of several files assembles each one and lists all objects on the
`sra8-ld` command line.

`program.mem` then replaces the file of the same name in the RTL folder
(copying it there is the user's step, not the kit's).

---

## 8. Tests (`tests/`, run with `make test`)

`[DECISION: default = Python `unittest`, no third-party test runner. The
C port has its own POSIX shell suite, `c/tests/run.sh`]`

The kit contains no emulator `[AUTHOR]`, so the tests verify encodings,
file formats and generated text. Run-time behaviour is verified by the
author on the FPGA.

1. **ISA table self-checks**: every opcode 0…113 has exactly one mnemonic
   or is listed as undefined; operand formats match `control_rom_gen.c`
   (the test parses the opcode enum of that file from the RTL folder when
   it is present).
2. **Encoding vectors** from 2.7 and from `f.l` (parse `f.l`: address,
   bytes, source; assemble and link the ported `loader.s` and compare every
   line).
3. **Legacy golden tests**: for each of `echo.s`, `loader.s`,
   `terminal.s`, `user_echo.s`, `asm/example.s`, `asm/demo.s`: the ported
   copy (3.10), assembled with `sra8-as` and linked with `flat.ld`, gives a
   `.bin` and a `.mem` that are byte-identical to the output of the legacy
   assembler run on the original file. The expected files are generated
   once from the RTL folder (`make golden`) and checked in under
   `tests/golden/`.
4. **Assembler negatives**: each removed feature of 3.10 is rejected with
   a clear message; undefined reference without `.import`; export of an
   undefined label; instruction in `.data`; anything but `.res` in `.bss`;
   instruction at an unaligned offset; value out of range.
5. **Linker**: two objects with cross references; duplicate export;
   unresolved import; script symbols (`symbol`, `start`, `last`); named
   sections and `*`; unplaced section error; region overflow; `align`;
   automatic 4-alignment of code sections; `bss` excluded from the image;
   `mem` and `ihex` writers.
6. **Disassembler round trip**: disassemble linked images, re-assemble and
   re-link, compare.
6a. **Generated files**: `docs/isa.md` and the VS Code grammar equal what
   the C port's `isagen` produces from its own table.
---

## 9. Repository layout

```
sra8-dev/
├── SRA8_DEVKIT_SPEC.md        this file
├── Changes.txt                the author's change list (applied)
├── README.md                  quick start, pipeline diagram, tool synopsis
├── Makefile                   test, examples, docs
├── bin/                       launchers: sra8-as sra8-ld sra8-objdump
├── sra8/                      Python package
│   ├── isa.py                 THE instruction table, formats, conditions, encode/decode helpers
│   ├── asm/                   preprocess.py parser.py assembler.py listing.py __main__.py
│   ├── obj.py                 object file read/write
│   ├── ld/                    script.py layout.py output.py __main__.py
│   └── objdump.py
├── ldscripts/                 boot.ld flat.ld
├── examples/
│   ├── Makefile               the build steps of Section 7
│   └── asm/                   echo.s loader.s terminal.s user_echo.s example.s demo.s (ported, 3.10)
├── tests/                     unittest suite, make_golden.py, golden/
├── vscode/sra8-lang/          VS Code extension: grammars for .s and .ld, gen_grammars.py
├── docs/                      isa.md (generated), asm.md, ld.md, obj.md
└── c/                         the C23 port: Makefile, src/, tests/run.sh, .clangd
```

`docs/isa.md` is **generated** from `sra8/isa.py` by `make docs` so the
tables never drift from the code.

---

## 10. Generation instructions (the prompt)

You are generating the SRA-8 development kit described above. Work in
`sra8-dev/`; read (only) `../sra-8-fpga/sra-8-fpga/` for ground truth.

1. **Re-derive, don't trust.** Before changing `sra8/isa.py`, parse
   `control_unit_gen/control_rom_gen.c` (opcode enum and microcode table),
   `InstructionRegister.v` (bit fields), `ControlUnit.v` (condition table,
   MUX decode, interrupt logic), `ALU.v` (flag rules) and
   `asm/sra8asm.py` (operand formats). Confirm every number in Section 2.
   Where this document is wrong, follow the RTL and list the difference in
   your final report under "Spec corrections".
2. Build in this order, testing each layer before the next:
   `isa.py` → assembler → object format → linker and scripts (pass the six
   golden tests) → objdump → docs → README.
3. Build **exactly the three tools** of 1.2. Do not build an emulator, an
   archiver or an uploader. Do not add assembler or
   linker features beyond Sections 3 to 5.
4. Respect every `[AUTHOR]` item and every `[DECISION]` default. Where a
   `[VERIFY]` item is unresolved, implement the RTL behaviour.
5. Every tool runs via its launcher in `bin/` and as a module:
   `python3 -m sra8.asm`, `python3 -m sra8.ld`, `python3 -m sra8.objdump`.
   No dependencies outside the standard
   library. Python 3.10+. A change in behaviour must also be made in the
   C port in `c/`, or the C tests will show the difference.
6. Code quality: type hints, docstrings on public functions, no function
   longer than ~80 lines without reason, error messages with `file:line`.
   Deterministic output. No hidden global state.
7. Finish with `make test` green and a final report containing: the tree
   of created files, test results, spec corrections, the list of
   `[VERIFY]` items still open, and the exact commands to rebuild
   `program.mem` for the FPGA from `examples/asm/terminal.s`.

---

## 11. Decisions log

Requirements from the author (`Changes.txt`), binding:

| # | Topic | Requirement |
|---|---|---|
| A2 | Tools | no `sra8-ar`, `sra8-emu`, `sra8-upload` |
| A3 | ALU | `SUBC` is repaired in the RTL (`a − b − 1 + C`); `MOVS`, `MVN`, `MVNS` are removed |
| A4 | Loader | `loader.s` and its protocol are temporary; the kit does not target them |
| A5 | Assembler comments | `;` only |
| A6 | Linkage | `.import` / `.export` only; no implicit import; no weak symbols; no `.equ` / `.set` |
| A7 | Operands | `#imm`, `=label`, `=label ± const`; no other expressions, no current-address operator, no `lo` / `hi` |
| A8 | Pseudo-instructions | none |
| A9 | Sections | `.code`, `.data`, `.bss`, each with an optional name; nothing else; no `.org`, no `.align` |
| A10 | Assembler extras | no `.incbin`, no new preprocessor directives, no `--image` |
| A11 | Object file | JSON |
| A12 | Linker script | minimal, clean syntax |

Defaults chosen in this document, open to change:

| # | Topic | Default |
|---|---|---|
| D1 | Implementation | Python 3.10+, stdlib only `[AUTHOR]`; C23 port in `c/` |
| D2 | Case sensitivity (asm) | mnemonics/registers insensitive, labels sensitive |
| D3 | Unaligned instruction in a code section | error, no automatic padding |
| D4 | Data directives | the legacy set only (no `.fill`, `.space`) |
| D5 | Unnamed section selector in scripts | `code` = unnamed, `code NAME`, `code *` |
| D6 | Unplaced sections | link error |
| D7 | Output formats | bin, mem, ihex, map |
| D8 | Built-in scripts | `boot.ld` (default), `flat.ld` |
| D25 | Tests | `unittest` (C port: shell script); goldens from the legacy assembler; no execution |

## 12. Open questions for the author (all `[VERIFY]` items collected)

Resolved by `Changes.txt` or by the RTL since the first version: `SUBC`
semantics (fixed), `MOVS` / `MVN` / `MVNS` (removed), UART baud rate
(115200 since RTL commit "USB serial port").

Still open:

1. RAM: is the full 64 KiB of `Memory.v` really usable, or should the
   default linker script assume less? (2.1, 5.5)
2. `INTPC` resets to 0 whenever not interrupted (RTL) vs. persists
   (program comments). Which is intended? Either way the vector convention
   of 2.8.3 works. (2.2)
3. PSR bit 4 reserved for something? (2.2)
4. Page table entry high byte reserved for a valid bit / page faults? (2.3)
5. No privileged instructions — intended? (2.2)
6. INTR `pf` / `ini` bit swap in `INTR.v` — irrelevant today, noted. (2.2)
7. `control_rom_gen.c` and `sra8asm.py` still mention `MOVS` / `MVN` in
   comments and in the `UNIMPLEMENTED` list, and `Instructions.xlsx` may
   still list them. Harmless for the kit; noted for consistency. (2.6)
