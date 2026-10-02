# SRA-8 instruction set

Generated from the instruction table (`sra8/isa.py`, mirrored by `c/src/common/isa.c`) with `make docs`. Do not edit.

## Instruction word

32 bit, stored big-endian (the byte at the lowest address holds bits 31:24).

| Bits | Field |
|---|---|
| 31:28 | condition |
| 27 | unused, 0 |
| 26:20 | opcode; bit 20 = immediate form |
| 19:16 | arg1 |
| 15:12 | arg2 |
| 11:8 | arg3 |
| 7:0 | imm8 |
| 15:0 | imm16 (overlaps arg2 and arg3) |

Register operands fill arg1, arg2, arg3 in the order they are written. `rNa` is the pair r(N+1):rN, low byte in rN; r15a wraps to r0 as the high byte.

## Operand formats

| Format | Operands |
|---|---|
| NONE | — |
| RD | rD |
| RDA | rDa |
| SRC8 | rS / #imm8 |
| SRC16 | rSa / #imm16 |
| RD_SRC8 | rD, rS / #imm8 |
| RD_SRC16 | rD, rSa / #imm16 |
| RDA_SRC16 | rDa, rSa / #imm16 |
| ALU3 | rD, rN, rM / #imm8 |

## Conditions

Written as a suffix: `add.eq r1, r2, r3`. A false condition costs 48 clocks and changes nothing.

| Code | Suffix | True when |
|---|---|---|
| 0 | `al` | always |
| 1 | `eq` | Z |
| 2 | `mi` | N |
| 3 | `vs` | V |
| 4 | `su` | ¬C (unsigned <) |
| 5 | `gu` | C ∧ ¬Z (unsigned >) |
| 6 | `ss` | N ⊕ V (signed <) |
| 7 | `gs` | ¬(N ⊕ V) ∧ ¬Z (signed >) |
| 8 | `nvr` | never |
| 9 | `ne` | ¬Z |
| 10 | `pl` | ¬N |
| 11 | `vc` | ¬V |
| 12 | `geu` | C (unsigned ≥) |
| 13 | `seu` | ¬C ∨ Z (unsigned ≤) |
| 14 | `ges` | ¬(N ⊕ V) (signed ≥) |
| 15 | `ses` | (N ⊕ V) ∨ Z (signed ≤) |

## ALU operations

Z = result is 0, N = bit 7 of the result for every operation.

| Code | Operation | Result | C | V |
|---|---|---|---|---|
| 0 | ADD | a + b | carry out | signed overflow |
| 1 | ADDC | a + b + C | carry out | signed overflow |
| 2 | SUB | a − b | ¬borrow (a ≥ b unsigned) | signed overflow |
| 3 | SUBC | a − b − 1 + C | ¬borrow | signed overflow |
| 4 | AND | a ∧ b | 0 | 0 |
| 5 | OR | a ∨ b | 0 | 0 |
| 6 | EOR | a ⊕ b | 0 | 0 |
| 7 | LSL | a << 1 | old a7 | 0 |
| 8 | LSR | a >> 1, logical | old a0 | 0 |
| 9 | ASR | a >> 1, sign kept | old a0 | 0 |
| 10 | CSL | {a[6:0], C} | old a7 | 0 |
| 11 | CSR | {C, a[7:1]} | old a0 | 0 |

## Instructions

Cycles = 4 × (11 fetch steps + steps), at 12 MHz.

### Register and system register moves

| Mnemonic | Operands | Reg | Imm | Steps | Cycles | Meaning |
|---|---|---|---|---|---|---|
| `mov` | rD, rS / #imm8 | 0 | 1 | 2 | 52 | rD ← src |
| `mova` | rDa, rSa / #imm16 | 2 | 3 | 3 | 56 | rDa ← src |
| `pcw` | rSa / #imm16 | 4 | 5 | 3 | 56 | PC ← src |
| `pcr` | rDa | 6 | — | 3 | 56 | rDa ← PC |
| `xpcw` | rSa / #imm16 | 8 | 9 | 3 | 56 | current PC ← src (PC, or INTPC while interrupted) |
| `xpcr` | rDa | 10 | — | 3 | 56 | rDa ← current PC (address of the next instruction) |
| `intpcw` | rSa / #imm16 | 12 | 13 | 3 | 56 | INTPC ← src |
| `intpcr` | rDa | 14 | — | 3 | 56 | rDa ← INTPC |
| `psrw` | rS / #imm8 | 16 | 17 | 2 | 52 | PSR ← src |
| `psrr` | rD | 18 | — | 2 | 52 | rD ← PSR |
| `ptbrw` | rSa / #imm16 | 20 | 21 | 3 | 56 | PTBR ← src |
| `ptbrr` | rDa | 22 | — | 3 | 56 | rDa ← PTBR |
| `intrw` | rS / #imm8 | 24 | 25 | 2 | 52 | INTR ← 0 (the value is ignored) |
| `intrr` | rD | 26 | — | 2 | 52 | rD ← INTR |

### Memory

| Mnemonic | Operands | Reg | Imm | Steps | Cycles | Meaning |
|---|---|---|---|---|---|---|
| `ldr` | rD, rSa / #imm16 | 28 | 29 | 6 | 68 | rD ← mem[addr] |
| `str` | rD, rSa / #imm16 | 30 | 31 | 6 | 68 | mem[addr] ← rS  (source register first) |

### Arithmetic and logic: rD = rN op (rM | imm8)

| Mnemonic | Operands | Reg | Imm | Steps | Cycles | Meaning |
|---|---|---|---|---|---|---|
| `add` | rD, rN, rM / #imm8 | 32 | 33 | 4 | 60 | rD ← rN + src |
| `adds` | rD, rN, rM / #imm8 | 34 | 35 | 4 | 60 | rD ← rN + src, flags |
| `addc` | rD, rN, rM / #imm8 | 36 | 37 | 4 | 60 | rD ← rN + src + C |
| `addcs` | rD, rN, rM / #imm8 | 38 | 39 | 4 | 60 | rD ← rN + src + C, flags |
| `sub` | rD, rN, rM / #imm8 | 40 | 41 | 4 | 60 | rD ← rN − src |
| `subs` | rD, rN, rM / #imm8 | 42 | 43 | 4 | 60 | rD ← rN − src, flags |
| `subc` | rD, rN, rM / #imm8 | 44 | 45 | 4 | 60 | rD ← rN − src − 1 + C |
| `subcs` | rD, rN, rM / #imm8 | 46 | 47 | 4 | 60 | rD ← rN − src − 1 + C, flags |
| `and` | rD, rN, rM / #imm8 | 48 | 49 | 4 | 60 | rD ← rN ∧ src |
| `ands` | rD, rN, rM / #imm8 | 50 | 51 | 4 | 60 | rD ← rN ∧ src, flags |
| `or` | rD, rN, rM / #imm8 | 52 | 53 | 4 | 60 | rD ← rN ∨ src |
| `ors` | rD, rN, rM / #imm8 | 54 | 55 | 4 | 60 | rD ← rN ∨ src, flags |
| `eor` | rD, rN, rM / #imm8 | 56 | 57 | 4 | 60 | rD ← rN ⊕ src |
| `eors` | rD, rN, rM / #imm8 | 58 | 59 | 4 | 60 | rD ← rN ⊕ src, flags |

### Shifts by one bit: rD = op(rS | imm8)

| Mnemonic | Operands | Reg | Imm | Steps | Cycles | Meaning |
|---|---|---|---|---|---|---|
| `lsl` | rD, rS / #imm8 | 60 | 61 | 3 | 56 | rD ← src << 1 |
| `lsls` | rD, rS / #imm8 | 62 | 63 | 3 | 56 | rD ← src << 1, flags |
| `lsr` | rD, rS / #imm8 | 64 | 65 | 3 | 56 | rD ← src >> 1 |
| `lsrs` | rD, rS / #imm8 | 66 | 67 | 3 | 56 | rD ← src >> 1, flags |
| `asr` | rD, rS / #imm8 | 68 | 69 | 3 | 56 | rD ← src >> 1, sign kept |
| `asrs` | rD, rS / #imm8 | 70 | 71 | 3 | 56 | rD ← src >> 1, sign kept, flags |
| `csl` | rD, rS / #imm8 | 72 | 73 | 3 | 56 | rD ← {src[6:0], C} |
| `csls` | rD, rS / #imm8 | 74 | 75 | 3 | 56 | rD ← {src[6:0], C}, flags |
| `csr` | rD, rS / #imm8 | 76 | 77 | 3 | 56 | rD ← {C, src[7:1]} |
| `csrs` | rD, rS / #imm8 | 78 | 79 | 3 | 56 | rD ← {C, src[7:1]}, flags |

### Flags only, result discarded

| Mnemonic | Operands | Reg | Imm | Steps | Cycles | Meaning |
|---|---|---|---|---|---|---|
| `cmn` | rD, rS / #imm8 | 80 | 81 | 4 | 60 | flags of rN + src |
| `addcd` | rD, rS / #imm8 | 82 | 83 | 4 | 60 | flags of rN + src + C |
| `cmp` | rD, rS / #imm8 | 84 | 85 | 4 | 60 | flags of rN − src |
| `subcd` | rD, rS / #imm8 | 86 | 87 | 4 | 60 | flags of rN − src − 1 + C |
| `andd` | rD, rS / #imm8 | 88 | 89 | 4 | 60 | flags of rN ∧ src |
| `ord` | rD, rS / #imm8 | 90 | 91 | 4 | 60 | flags of rN ∨ src |
| `eord` | rD, rS / #imm8 | 92 | 93 | 4 | 60 | flags of rN ⊕ src |
| `lsld` | rS / #imm8 | 94 | 95 | 3 | 56 | flags of src << 1 |
| `lsrd` | rS / #imm8 | 96 | 97 | 3 | 56 | flags of src >> 1 |
| `asrd` | rS / #imm8 | 98 | 99 | 3 | 56 | flags of src >> 1, sign kept |
| `csld` | rS / #imm8 | 100 | 101 | 3 | 56 | flags of {src[6:0], C} |
| `csrd` | rS / #imm8 | 102 | 103 | 3 | 56 | flags of {C, src[7:1]} |

### Control flow

| Mnemonic | Operands | Reg | Imm | Steps | Cycles | Meaning |
|---|---|---|---|---|---|---|
| `br` | rSa / #imm16 | 104 | 105 | 3 | 56 | current PC ← target |
| `brl` | rDa, rSa / #imm16 | 106 | 107 | 5 | 64 | rLa ← address of next instruction; current PC ← target |

### I/O and other

| Mnemonic | Operands | Reg | Imm | Steps | Cycles | Meaning |
|---|---|---|---|---|---|---|
| `ptr` | rD | 108 | — | 2 | 52 | rD ← received UART byte; clears the port IRQ line |
| `ptw` | rD | 110 | — | 2 | 52 | send rS on the UART (no busy flag) |
| `svc` | — | 112 | — | 2 | 52 | supervisor call: enter interrupt mode |

## Undefined opcodes

7, 11, 15, 19, 23, 27, 109, 111, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127.

Their microcode is all zero and never returns to fetch: executing one is destructive. The assembler cannot produce them.
