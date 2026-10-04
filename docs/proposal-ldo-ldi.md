# Proposal: offset and post-increment addressing (`ldo`, `sto`, `ldi`, `sti`, `lea`)

**Status: implemented** (2026-10-04) in the RTL (`CPU.v`, `ControlUnit.v`,
`MAR.v`, `InstructionRegister.v`, `control_unit_gen/*.c`, the ROM images)
and in the toolchain. Bit 2 of the control word and MUX 1 codes 28 … 31 stay
unused. The microcode in `control_rom_gen.c` lists every step of every
opcode explicitly; section 4 shows the steps in a shorter form.

## 1. The instructions

| Syntax | Meaning | Steps | Cycles |
|---|---|---|---|
| `ldo rD, rBa, #off` / `rOa` | rD ← mem[rBa + offset] | 8 | 76 |
| `sto rS, rBa, #off` / `rOa` | mem[rBa + offset] ← rS | 8 | 76 |
| `ldi rD, rBa, #inc` / `rOa` | rD ← mem[rBa], then rBa ← rBa + increment | 10 | 84 |
| `sti rS, rBa, #inc` / `rOa` | mem[rBa] ← rS, then rBa ← rBa + increment | 10 | 84 |
| `lea rDa, rBa, #off` / `rOa` | rDa ← rBa + offset (no memory access) | 7 | 72 |

- `off` / `inc` is a **signed 12-bit** immediate, −2048 … 2047; `rOa` is a
  16-bit register pair. Sums wrap modulo 2¹⁶. Register and immediate forms
  take the same number of steps.
- The address is formed **before** translation, as for `ldr` / `str`: MAR
  holds the untranslated address throughout.
- **No flags change.** The sums use an adder in MAR, not the ALU.
- With a negative increment `ldi` / `sti` walk downwards (`sti r0, r14a, #-1`
  pushes a byte).
- For comparison: `ldr` is 6 steps (68 cycles); `ldr` from SP + k takes
  `adds` + `addc` + `ldr` today, 3 instructions, 188 cycles.
- **`ldi` with rD inside rBa** (rD = rB or rB+1) is allowed: the byte is
  loaded first, then the base write-back overwrites it, so the register ends
  up holding its part of the new base. The assembler does not reject it.

## 2. Encoding and opcodes

```
 31   28 27 26      20 19    16 15    12 11     8 7        0
┌───────┬──┬──────────┬────────┬────────┬───────────────────┐
│ cond  │0 │  opcode  │ rD/rS  │   rB   │ off12 (imm form)  │
│       │  │          │        │        │ rO    │ 0 (reg)   │
└───────┴──┴──────────┴────────┴────────┴───────────────────┘
```

Bits 19:16 hold rD (`ldo`, `ldi`), rS (`sto`, `sti`) or rDa (`lea`).

The new instructions go right **behind `ldr` / `str`**, and every opcode
from `add` on moves up by 10:

| Opcodes | Instructions | Change |
|---|---|---|
| 0 … 31 | `mov` … `intrr`, `ldr`, `str` | unchanged |
| 32 / 33 | `ldo` | new |
| 34 / 35 | `sto` | new |
| 36 / 37 | `ldi` | new |
| 38 / 39 | `sti` | new |
| 40 / 41 | `lea` | new |
| 42 … 113 | `add` … `csrd` | were 32 … 103 |
| 114 … 121 | `br`, `brl`, `ptr`, `ptw` | were 104 … 111 |
| 122 | `svc` | was 112 |
| 123 … 127 | free | |

**Consequence:** every existing binary changes, since most opcodes move. To
be redone afterwards: `program.mem` of every program; the legacy assembler
in the RTL folder (`asm/sra8asm.py`, `asm/sra8asm.c`) and with it the golden
files of the kit (`make golden`); `f.l`, which the kit's tests use as
encoding vectors.

## 3. Hardware changes

### 3.1 `InstructionRegister.v`

- Rename `imm0_out` → `imm_byte0_out` and `imm1_out` → `imm_byte1_out`.
- New outputs, the sign-extended 12-bit offset as two bytes:

  ```verilog
  assign off12_byte0_out = instruction[7:0];
  assign off12_byte1_out = {{4{instruction[11]}}, instruction[11:8]};
  ```

### 3.2 `MAR.v`

| New port | Meaning |
|---|---|
| `add_en` (`mar_add`) | byte_sel = 0: byte_0 ← byte_0 + bus, carry → `add_carry`; byte_sel = 1: byte_1 ← byte_1 + bus + `add_carry` |
| `read_en` (`mar_read`), `bus_out[7:0]` | the (untranslated) MAR byte selected by byte_sel onto the bus |

`add_carry` is a flip-flop of MAR, not PSR.C. Updates on phase 2, like the
existing writes.

### 3.3 `ControlUnit.v`: the control word

**MUX 4 goes away.** Its two jobs move into MUX 1, which grows to 5 bits:

- *Which register a GR read uses* (MUX 4 = arg1 / arg2 / arg3 together with
  MUX 1 = `gr_read`) becomes three MUX 1 codes, `gr_read_arg1`,
  `gr_read_arg2`, `gr_read_arg3`.
- *The ALU operation* (MUX 4 : MUX 5 = `alu_opcode` on ALU steps) becomes
  one MUX 1 code per operation. Every ALU step already drives the bus with
  `alu_read`, the flags-only ones (`cmp` …) included, so nothing is lost.

New layout, still 16 bits:

```
 15     11 10      6 5    3  2  1   0
┌─────────┬─────────┬──────┬───┬─────┐
│  MUX 1  │  MUX 2  │ MUX 3│ – │MUX 5│      bit 2: spare, 0
└─────────┴─────────┴──────┴───┴─────┘
```

MUX 1, 5 bits (source on the bus):

| Code | Signal | Code | Signal |
|---|---|---|---|
| 0 | none | 9 | `psr_read` |
| 1 | `gr_read_arg1` | 10 | `ptbr_read` |
| 2 | `gr_read_arg2` | 11 | `intr_read` |
| 3 | `gr_read_arg3` | 12 | `port_read` |
| 4 | `mem_read` | 13 | `btrom_read` |
| 5 | `imm_read` | 14 | `off12_read` (new) |
| 6 | `pc_read` | 15 | `mar_read` (new) |
| 7 | `intpc_read` | 16 … 27 | `alu_read`, operation = code − 16 (`ALU_ADD` … `ALU_CSR`) |
| 8 | `xpc_read` | 28 … 31 | free |

MUX 2 (5 bits) keeps its codes and gains two:

| Code | Signal | Meaning |
|---|---|---|
| 18 | `mar_add` | MAR byte (byte_sel) += bus |
| 19 | `gr_write_base` | GR[arg2 + byte_sel] ← bus: the base write-back of `ldi` / `sti` |

MUX 3 and MUX 5 are unchanged.

```verilog
wire [4:0] mux1 = ucode[15:11];
wire [4:0] mux2 = ucode[10:6];
wire [2:0] mux3 = ucode[5:3];
wire [1:0] mux5 = ucode[1:0];

assign gr_read      = mux1 == 1 | mux1 == 2 | mux1 == 3;
assign gr_read_sel  = (mux1 == 1 ? arg1 : mux1 == 2 ? arg2 : arg3) + byte_sel;
assign alu_read     = mux1[4];                 // codes 16 ... 31
assign alu_opcode   = mux1[3:0];
assign off12_read   = mux1 == 14;
assign mar_read     = mux1 == 15;
assign mar_add      = mux2 == 18;
assign gr_write_base = mux2 == 19;
assign gr_write     = mux2 == 1 | gr_write_base;
assign gr_write_sel = (gr_write_base ? arg2 : arg1) + byte_sel;
assign bus_out = (imm_read   ? (byte_sel ? imm_byte1   : imm_byte0)   : 8'b0)
               | (off12_read ? (byte_sel ? off12_byte1 : off12_byte0) : 8'b0);
```

`mem_read`, `imm_read` … `btrom_read` compare against their new codes; the
special case that zeroes MUX 4 / MUX 5 on ALU steps is no longer needed.

**Constants that depend on the layout** must be recomputed:

| Where | Today | New |
|---|---|---|
| idle / `ucr` word, `16'h0050` (several places in `ControlUnit.v`) | MUX 3 = 5 at bits 6:4 | MUX 3 = 5 at bits 5:3: `16'h0028` |
| `BOOT_UCODE = 16'hC250` | btrom_read 12, mem_write 4, ucr 5 | btrom_read 13, mem_write 4, ucr 5: `16'h6928` |
| `fetch.mem` (`fetch_rom_gen.c`) | old layout | regenerated with the new `STEP` macro |

**16 steps per opcode** (`ldi` / `sti` need 10; today there are 8):

- `ControlUnit.v`: `instr_ucode [0:(1<<11)-1]`, index `(step - 11) | (opcode << 4)`.
- `control_rom_gen.c`: `STEP_BITS 4`; 2048 words, 8 block RAMs instead of 4
  (the UP5K has 30).
- `UC.v`: unchanged; its 5-bit counter reaches 11 + 16.

### 3.4 Both ROM generators

`control_rom_gen.c` and `fetch_rom_gen.c` get the new enums and a
four-field `STEP(m1, m2, m3, m5)`; `ALU_STEP` disappears. Rewriting the
existing microcode is mechanical:

| Today | New |
|---|---|
| `STEP(M1_GR_READ, m2, m3, M4_GR_SEL_ARGn, m5)` | `STEP(M1_GR_READ_ARGn, m2, m3, m5)` |
| `ALU_STEP(M1_ALU_READ, m2, m3, ALU_op)` | `STEP(M1_ALU(ALU_op), m2, m3, M5_NONE)`, with `#define M1_ALU(op) (16 + (op))` |
| `STEP(m1, m2, m3, M4_NONE, m5)` | `STEP(m1, m2, m3, m5)` |

### 3.5 `CPU.v`

Wire the new signals; `mar_bus` joins the bus OR.

## 4. Microcode (shorthand; `control_rom_gen.c` spells out every step)

Six building blocks; `LDR`'s base and walk steps are reused unchanged.

```c
/* base -> MAR (as LDR) */
#define BASE_TO_MAR \
    STEP(M1_GR_READ_ARG2, M2_MAR_WRITE,     M3_NONE,     M5_NONE), \
    STEP(M1_GR_READ_ARG2, M2_MAR_WRITE,     M3_BYTE_SEL, M5_NONE)
/* MAR += off12 (immediate forms) */
#define ADD_OFF12 \
    STEP(M1_OFF12_READ,   M2_MAR_ADD,       M3_NONE,     M5_NONE), \
    STEP(M1_OFF12_READ,   M2_MAR_ADD,       M3_BYTE_SEL, M5_NONE)
/* MAR += rOa (register forms) */
#define ADD_ROA \
    STEP(M1_GR_READ_ARG3, M2_MAR_ADD,       M3_NONE,     M5_NONE), \
    STEP(M1_GR_READ_ARG3, M2_MAR_ADD,       M3_BYTE_SEL, M5_NONE)
/* page-table walk (as LDR) */
#define WALK \
    STEP(M1_MEM_READ,     M2_PTER_WRITE,    M3_NONE,     M5_PTBR_ADDR_READ), \
    STEP(M1_MEM_READ,     M2_PTER_WRITE,    M3_BYTE_SEL, M5_PTBR_ADDR_READ)
/* MAR -> base pair (ldi, sti) */
#define MAR_TO_BASE \
    STEP(M1_MAR_READ,     M2_GR_WRITE_BASE, M3_NONE,     M5_NONE), \
    STEP(M1_MAR_READ,     M2_GR_WRITE_BASE, M3_BYTE_SEL, M5_NONE)
/* MAR -> rDa (lea) */
#define MAR_TO_DEST \
    STEP(M1_MAR_READ,     M2_GR_WRITE,      M3_NONE,     M5_NONE), \
    STEP(M1_MAR_READ,     M2_GR_WRITE,      M3_BYTE_SEL, M5_NONE)

#define LOAD   STEP(M1_MEM_READ,     M2_GR_WRITE,  M3_NONE, M5_X_ADDR_READ)
#define STORE  STEP(M1_GR_READ_ARG1, M2_MEM_WRITE, M3_NONE, M5_X_ADDR_READ)

[OPC_LDO_I] = { BASE_TO_MAR, ADD_OFF12, WALK, LOAD,  UCR_STEP },             /*  8 */
[OPC_LDO]   = { BASE_TO_MAR, ADD_ROA,   WALK, LOAD,  UCR_STEP },             /*  8 */
[OPC_STO_I] = { BASE_TO_MAR, ADD_OFF12, WALK, STORE, UCR_STEP },             /*  8 */
[OPC_STO]   = { BASE_TO_MAR, ADD_ROA,   WALK, STORE, UCR_STEP },             /*  8 */
[OPC_LDI_I] = { BASE_TO_MAR, WALK, LOAD,  ADD_OFF12, MAR_TO_BASE, UCR_STEP }, /* 10 */
[OPC_LDI]   = { BASE_TO_MAR, WALK, LOAD,  ADD_ROA,   MAR_TO_BASE, UCR_STEP }, /* 10 */
[OPC_STI_I] = { BASE_TO_MAR, WALK, STORE, ADD_OFF12, MAR_TO_BASE, UCR_STEP }, /* 10 */
[OPC_STI]   = { BASE_TO_MAR, WALK, STORE, ADD_ROA,   MAR_TO_BASE, UCR_STEP }, /* 10 */
[OPC_LEA_I] = { BASE_TO_MAR, ADD_OFF12, MAR_TO_DEST, UCR_STEP },             /*  7 */
[OPC_LEA]   = { BASE_TO_MAR, ADD_ROA,   MAR_TO_DEST, UCR_STEP },             /*  7 */
```

## 5. Toolchain changes

- `sra8/isa.py`, `c/src/common/isa.c`: the new opcode table, the five
  instructions, a new operand format `rD, rBa, #off12 | rOa` with the 12-bit
  immediate in bits 11:0; regenerate `docs/isa.md` and the VS Code grammar.
- Assembler and disassembler: the new format and range; `ldi` / `sti` with
  rD inside rBa accepted.
- Tests: the opcode check against `control_rom_gen.c` as now; new encoding
  vectors; goldens and `f.l` regenerated once the legacy assembler is
  updated.
- Still to do — ylangc 0.3: stack frames (`ldo` / `sto rD, r14a, #k`, frame allocation
  `lea r14a, r14a, #-F`), so every function is re-entrant and `@recursive`,
  frame copies, headers and the cycle check go away; fields through pointers
  as one `ldo`; copy loops with `ldi` / `sti`.

## 6. Verification

- The rewrite of the existing microcode is mechanical; decoding the old and
  the new `control_rom.mem` / `fetch.mem` into signals gives the same steps
  for every existing opcode at its new number.
- Icarus Verilog runs of the RTL: a test of every form of the new
  instructions (offsets ±, the ±2048 extremes, carry and 64 KiB wrap,
  post-increment both ways, `ldi` into its own base, false conditions,
  flags unchanged), and one under address translation (pl 1, an offset
  crossing from one virtual page into another mapped elsewhere), match the
  expected values; compiled Y programs match an instruction-level
  simulator byte for byte.
- `yosys` + `nextpnr` for the iCEBreaker: fits (1379 / 5280 LCs, 8 / 30
  block RAMs) and passes 12 MHz (22.9 MHz maximum).
