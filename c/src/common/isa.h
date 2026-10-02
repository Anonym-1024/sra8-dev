/* isa.h -- the SRA-8 instruction set: the single source of truth.
 *
 * Derived from the RTL in ../sra-8-fpga/sra-8-fpga:
 *   opcode numbers, operand order   control_unit_gen/control_rom_gen.c
 *   instruction word fields         InstructionRegister.v
 *   conditions                      ControlUnit.v
 *   ALU operations and flags        ALU.v
 *   microstep counts                control_rom.mem (position of the ucr step)
 *
 * No other file may hardcode an opcode number.  `isagen markdown` prints
 * the tables (docs/isa.md), `isagen check-rtl DIR` checks them against the
 * RTL.
 */
#ifndef SRA8_ISA_H
#define SRA8_ISA_H

#include "util.h"

constexpr int ISA_INSTR_SIZE = 4;       /* bytes, stored big-endian */
constexpr int ISA_PAGE_SIZE = 256;
constexpr long ISA_ADDR_SPACE = 1L << 16;
constexpr int ISA_FETCH_STEPS = 11;
constexpr int ISA_CLOCKS_PER_STEP = 4;
constexpr long ISA_CLOCK_HZ = 12'000'000;

typedef struct {
    const char *name;
    int nregs;          /* register operands before the source */
    int regs[2];        /* their widths: 8 or 16 */
    int src;            /* width of the last operand (register or immediate), 0 = none */
    const char *syntax;
} Format;

typedef struct {
    const char *mnemonic;
    int opcode;         /* register form; immediate form = opcode | 1 */
    const Format *fmt;
    int steps;          /* microsteps of the body, ucr step included */
    const char *group;
    const char *meaning;
    const char *alu;    /* ALU operation or nullptr */
    bool sets_flags;
} Instr;

typedef struct {
    const char *name;
    const char *meaning;
} Cond;

typedef struct {
    const char *name;
    const char *result, *c, *v;
} AluOp;

extern const Format ISA_FORMATS[];
extern const size_t ISA_N_FORMATS;
extern const Instr ISA_INSTRUCTIONS[];
extern const size_t ISA_N_INSTRUCTIONS;
extern const Cond ISA_CONDITIONS[16];
extern const AluOp ISA_ALU_OPS[];
extern const size_t ISA_N_ALU_OPS;
extern const char *const ISA_GROUPS[];
extern const size_t ISA_N_GROUPS;

static inline int fmt_operands(const Format *f) { return f->nregs + (f->src ? 1 : 0); }
static inline int isa_cycles(const Instr *ins) { return ISA_CLOCKS_PER_STEP * (ISA_FETCH_STEPS + ins->steps); }
constexpr int ISA_SKIPPED_CYCLES = 4 * (11 + 1);

const Instr *isa_find(const char *mnemonic);    /* lower case; nullptr if unknown */
int isa_cond(const char *name);                 /* -1 if unknown */
const Instr *isa_opcode(int opcode, bool *imm); /* nullptr for undefined opcodes */

/* -2**(bits-1) .. 2**bits - 1, returns the two's complement field. */
bool isa_fit(long long value, int bits, long long *field);

void isa_encode(uint8_t out[4], int cond, int opcode, const int args[3], long long imm);

typedef struct {
    int cond;
    const Instr *ins;
    bool imm_form;
    int regs[3];
    int nregs;
    long long imm;
} Decoded;

/* True only for words that are exactly what the assembler produces. */
bool isa_decode(const uint8_t word[4], Decoded *d);
/* "mnemonic[.cond] operands"; imm_text replaces the immediate if given. */
void isa_text(const Decoded *d, const char *imm_text, Str *out);

#endif
