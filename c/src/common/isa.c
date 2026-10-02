/* isa.c -- the SRA-8 instruction set tables, encoding and decoding. */
#include "isa.h"

#include <stdlib.h>
#include <string.h>

const Format ISA_FORMATS[] = {
    {"NONE", 0, {0, 0}, 0, ""},
    {"RD", 1, {8, 0}, 0, "rD"},
    {"RDA", 1, {16, 0}, 0, "rDa"},
    {"SRC8", 0, {0, 0}, 8, "rS / #imm8"},
    {"SRC16", 0, {0, 0}, 16, "rSa / #imm16"},
    {"RD_SRC8", 1, {8, 0}, 8, "rD, rS / #imm8"},
    {"RD_SRC16", 1, {8, 0}, 16, "rD, rSa / #imm16"},
    {"RDA_SRC16", 1, {16, 0}, 16, "rDa, rSa / #imm16"},
    {"ALU3", 2, {8, 8}, 8, "rD, rN, rM / #imm8"},
};
const size_t ISA_N_FORMATS = sizeof ISA_FORMATS / sizeof ISA_FORMATS[0];

#define F_NONE (&ISA_FORMATS[0])
#define F_RD (&ISA_FORMATS[1])
#define F_RDA (&ISA_FORMATS[2])
#define F_SRC8 (&ISA_FORMATS[3])
#define F_SRC16 (&ISA_FORMATS[4])
#define F_RD_SRC8 (&ISA_FORMATS[5])
#define F_RD_SRC16 (&ISA_FORMATS[6])
#define F_RDA_SRC16 (&ISA_FORMATS[7])
#define F_ALU3 (&ISA_FORMATS[8])

#define G_REG "Register and system register moves"
#define G_MEM "Memory"
#define G_ALU "Arithmetic and logic: rD = rN op (rM | imm8)"
#define G_SHIFT "Shifts by one bit: rD = op(rS | imm8)"
#define G_FLAGS "Flags only, result discarded"
#define G_BR "Control flow"
#define G_IO "I/O and other"

const char *const ISA_GROUPS[] = {G_REG, G_MEM, G_ALU, G_SHIFT, G_FLAGS, G_BR, G_IO};
const size_t ISA_N_GROUPS = sizeof ISA_GROUPS / sizeof ISA_GROUPS[0];

const Instr ISA_INSTRUCTIONS[] = {
    {"mov", 0, F_RD_SRC8, 2, G_REG, "rD ← src", nullptr, false},
    {"mova", 2, F_RDA_SRC16, 3, G_REG, "rDa ← src", nullptr, false},
    {"pcw", 4, F_SRC16, 3, G_REG, "PC ← src", nullptr, false},
    {"pcr", 6, F_RDA, 3, G_REG, "rDa ← PC", nullptr, false},
    {"xpcw", 8, F_SRC16, 3, G_REG, "current PC ← src (PC, or INTPC while interrupted)", nullptr, false},
    {"xpcr", 10, F_RDA, 3, G_REG, "rDa ← current PC (address of the next instruction)", nullptr, false},
    {"intpcw", 12, F_SRC16, 3, G_REG, "INTPC ← src", nullptr, false},
    {"intpcr", 14, F_RDA, 3, G_REG, "rDa ← INTPC", nullptr, false},
    {"psrw", 16, F_SRC8, 2, G_REG, "PSR ← src", nullptr, false},
    {"psrr", 18, F_RD, 2, G_REG, "rD ← PSR", nullptr, false},
    {"ptbrw", 20, F_SRC16, 3, G_REG, "PTBR ← src", nullptr, false},
    {"ptbrr", 22, F_RDA, 3, G_REG, "rDa ← PTBR", nullptr, false},
    {"intrw", 24, F_SRC8, 2, G_REG, "INTR ← 0 (the value is ignored)", nullptr, false},
    {"intrr", 26, F_RD, 2, G_REG, "rD ← INTR", nullptr, false},

    {"ldr", 28, F_RD_SRC16, 6, G_MEM, "rD ← mem[addr]", nullptr, false},
    {"str", 30, F_RD_SRC16, 6, G_MEM, "mem[addr] ← rS  (source register first)", nullptr, false},

    {"add", 32, F_ALU3, 4, G_ALU, "rD ← rN + src", "ADD", false},
    {"adds", 34, F_ALU3, 4, G_ALU, "rD ← rN + src, flags", "ADD", true},
    {"addc", 36, F_ALU3, 4, G_ALU, "rD ← rN + src + C", "ADDC", false},
    {"addcs", 38, F_ALU3, 4, G_ALU, "rD ← rN + src + C, flags", "ADDC", true},
    {"sub", 40, F_ALU3, 4, G_ALU, "rD ← rN − src", "SUB", false},
    {"subs", 42, F_ALU3, 4, G_ALU, "rD ← rN − src, flags", "SUB", true},
    {"subc", 44, F_ALU3, 4, G_ALU, "rD ← rN − src − 1 + C", "SUBC", false},
    {"subcs", 46, F_ALU3, 4, G_ALU, "rD ← rN − src − 1 + C, flags", "SUBC", true},
    {"and", 48, F_ALU3, 4, G_ALU, "rD ← rN ∧ src", "AND", false},
    {"ands", 50, F_ALU3, 4, G_ALU, "rD ← rN ∧ src, flags", "AND", true},
    {"or", 52, F_ALU3, 4, G_ALU, "rD ← rN ∨ src", "OR", false},
    {"ors", 54, F_ALU3, 4, G_ALU, "rD ← rN ∨ src, flags", "OR", true},
    {"eor", 56, F_ALU3, 4, G_ALU, "rD ← rN ⊕ src", "EOR", false},
    {"eors", 58, F_ALU3, 4, G_ALU, "rD ← rN ⊕ src, flags", "EOR", true},

    {"lsl", 60, F_RD_SRC8, 3, G_SHIFT, "rD ← src << 1", "LSL", false},
    {"lsls", 62, F_RD_SRC8, 3, G_SHIFT, "rD ← src << 1, flags", "LSL", true},
    {"lsr", 64, F_RD_SRC8, 3, G_SHIFT, "rD ← src >> 1", "LSR", false},
    {"lsrs", 66, F_RD_SRC8, 3, G_SHIFT, "rD ← src >> 1, flags", "LSR", true},
    {"asr", 68, F_RD_SRC8, 3, G_SHIFT, "rD ← src >> 1, sign kept", "ASR", false},
    {"asrs", 70, F_RD_SRC8, 3, G_SHIFT, "rD ← src >> 1, sign kept, flags", "ASR", true},
    {"csl", 72, F_RD_SRC8, 3, G_SHIFT, "rD ← {src[6:0], C}", "CSL", false},
    {"csls", 74, F_RD_SRC8, 3, G_SHIFT, "rD ← {src[6:0], C}, flags", "CSL", true},
    {"csr", 76, F_RD_SRC8, 3, G_SHIFT, "rD ← {C, src[7:1]}", "CSR", false},
    {"csrs", 78, F_RD_SRC8, 3, G_SHIFT, "rD ← {C, src[7:1]}, flags", "CSR", true},

    {"cmn", 80, F_RD_SRC8, 4, G_FLAGS, "flags of rN + src", "ADD", true},
    {"addcd", 82, F_RD_SRC8, 4, G_FLAGS, "flags of rN + src + C", "ADDC", true},
    {"cmp", 84, F_RD_SRC8, 4, G_FLAGS, "flags of rN − src", "SUB", true},
    {"subcd", 86, F_RD_SRC8, 4, G_FLAGS, "flags of rN − src − 1 + C", "SUBC", true},
    {"andd", 88, F_RD_SRC8, 4, G_FLAGS, "flags of rN ∧ src", "AND", true},
    {"ord", 90, F_RD_SRC8, 4, G_FLAGS, "flags of rN ∨ src", "OR", true},
    {"eord", 92, F_RD_SRC8, 4, G_FLAGS, "flags of rN ⊕ src", "EOR", true},
    {"lsld", 94, F_SRC8, 3, G_FLAGS, "flags of src << 1", "LSL", true},
    {"lsrd", 96, F_SRC8, 3, G_FLAGS, "flags of src >> 1", "LSR", true},
    {"asrd", 98, F_SRC8, 3, G_FLAGS, "flags of src >> 1, sign kept", "ASR", true},
    {"csld", 100, F_SRC8, 3, G_FLAGS, "flags of {src[6:0], C}", "CSL", true},
    {"csrd", 102, F_SRC8, 3, G_FLAGS, "flags of {C, src[7:1]}", "CSR", true},

    {"br", 104, F_SRC16, 3, G_BR, "current PC ← target", nullptr, false},
    {"brl", 106, F_RDA_SRC16, 5, G_BR, "rLa ← address of next instruction; current PC ← target", nullptr, false},

    {"ptr", 108, F_RD, 2, G_IO, "rD ← received UART byte; clears the port IRQ line", nullptr, false},
    {"ptw", 110, F_RD, 2, G_IO, "send rS on the UART (no busy flag)", nullptr, false},
    {"svc", 112, F_NONE, 2, G_IO, "supervisor call: enter interrupt mode", nullptr, false},
};
const size_t ISA_N_INSTRUCTIONS = sizeof ISA_INSTRUCTIONS / sizeof ISA_INSTRUCTIONS[0];

const Cond ISA_CONDITIONS[16] = {
    {"al", "always"}, {"eq", "Z"}, {"mi", "N"}, {"vs", "V"},
    {"su", "¬C (unsigned <)"}, {"gu", "C ∧ ¬Z (unsigned >)"},
    {"ss", "N ⊕ V (signed <)"}, {"gs", "¬(N ⊕ V) ∧ ¬Z (signed >)"},
    {"nvr", "never"}, {"ne", "¬Z"}, {"pl", "¬N"}, {"vc", "¬V"},
    {"geu", "C (unsigned ≥)"}, {"seu", "¬C ∨ Z (unsigned ≤)"},
    {"ges", "¬(N ⊕ V) (signed ≥)"}, {"ses", "(N ⊕ V) ∨ Z (signed ≤)"},
};

const AluOp ISA_ALU_OPS[] = {
    {"ADD", "a + b", "carry out", "signed overflow"},
    {"ADDC", "a + b + C", "carry out", "signed overflow"},
    {"SUB", "a − b", "¬borrow (a ≥ b unsigned)", "signed overflow"},
    {"SUBC", "a − b − 1 + C", "¬borrow", "signed overflow"},
    {"AND", "a ∧ b", "0", "0"},
    {"OR", "a ∨ b", "0", "0"},
    {"EOR", "a ⊕ b", "0", "0"},
    {"LSL", "a << 1", "old a7", "0"},
    {"LSR", "a >> 1, logical", "old a0", "0"},
    {"ASR", "a >> 1, sign kept", "old a0", "0"},
    {"CSL", "{a[6:0], C}", "old a7", "0"},
    {"CSR", "{C, a[7:1]}", "old a0", "0"},
};
const size_t ISA_N_ALU_OPS = sizeof ISA_ALU_OPS / sizeof ISA_ALU_OPS[0];

const Instr *isa_find(const char *mnemonic)
{
    for (size_t i = 0; i < ISA_N_INSTRUCTIONS; i++)
        if (strcmp(ISA_INSTRUCTIONS[i].mnemonic, mnemonic) == 0)
            return &ISA_INSTRUCTIONS[i];
    return nullptr;
}

int isa_cond(const char *name)
{
    for (int i = 0; i < 16; i++)
        if (strcmp(ISA_CONDITIONS[i].name, name) == 0)
            return i;
    return -1;
}

const Instr *isa_opcode(int opcode, bool *imm)
{
    for (size_t i = 0; i < ISA_N_INSTRUCTIONS; i++) {
        const Instr *ins = &ISA_INSTRUCTIONS[i];
        if (opcode == ins->opcode) {
            *imm = false;
            return ins;
        }
        if (ins->fmt->src && opcode == (ins->opcode | 1)) {
            *imm = true;
            return ins;
        }
    }
    return nullptr;
}

bool isa_fit(long long value, int bits, long long *field)
{
    long long lo = -(1LL << (bits - 1)), hi = (1LL << bits) - 1;
    if (value < lo || value > hi)
        return false;
    *field = value & ((1LL << bits) - 1);
    return true;
}

void isa_encode(uint8_t out[4], int cond, int opcode, const int args[3], long long imm)
{
    static const int shifts[3] = {16, 12, 8};
    uint32_t w = (uint32_t)(cond & 0xF) << 28 | (uint32_t)(opcode & 0x7F) << 20;
    for (int i = 0; i < 3; i++)
        w |= (uint32_t)(args[i] & 0xF) << shifts[i];
    w |= (uint32_t)(imm & 0xFFFF);
    out[0] = (uint8_t)(w >> 24);
    out[1] = (uint8_t)(w >> 16);
    out[2] = (uint8_t)(w >> 8);
    out[3] = (uint8_t)w;
}

bool isa_decode(const uint8_t word[4], Decoded *d)
{
    static const int shifts[3] = {16, 12, 8};
    uint32_t w = (uint32_t)word[0] << 24 | (uint32_t)word[1] << 16 | (uint32_t)word[2] << 8 | word[3];
    int cond = (int)(w >> 28 & 0xF);
    int opcode = (int)(w >> 20 & 0x7F);
    bool imm = false;
    const Instr *ins = (w >> 27 & 1) ? nullptr : isa_opcode(opcode, &imm);
    if (!ins)
        return false;
    *d = (Decoded){.cond = cond, .ins = ins, .imm_form = imm};
    d->nregs = ins->fmt->nregs + (ins->fmt->src && !imm ? 1 : 0);
    for (int i = 0; i < d->nregs; i++)
        d->regs[i] = (int)(w >> shifts[i] & 0xF);
    if (imm)
        d->imm = w & (ins->fmt->src == 8 ? 0xFFu : 0xFFFFu);
    uint8_t again[4];
    isa_encode(again, cond, opcode, d->regs, imm ? d->imm : 0);
    return memcmp(again, word, 4) == 0;
}

void isa_text(const Decoded *d, const char *imm_text, Str *out)
{
    const Format *f = d->ins->fmt;
    int widths[3], n = 0;
    for (int i = 0; i < f->nregs; i++)
        widths[n++] = f->regs[i];
    if (f->src)
        widths[n++] = f->src;
    Str name = {}, ops = {};
    str_add(&name, d->ins->mnemonic);
    if (d->cond)
        str_addf(&name, ".%s", ISA_CONDITIONS[d->cond].name);
    for (int i = 0; i < n; i++) {
        if (i)
            str_add(&ops, ", ");
        bool is_src = f->src && i == n - 1;
        if (is_src && d->imm_form) {
            if (imm_text)
                str_add(&ops, imm_text);
            else
                str_addf(&ops, "#0x%0*llX", widths[i] == 8 ? 2 : 4, d->imm);
        } else {
            str_addf(&ops, "r%d%s", d->regs[i], widths[i] == 16 ? "a" : "");
        }
    }
    if (n) {
        str_pad(out, str_cstr(&name), 7);
        str_addc(out, ' ');
        str_add(out, str_cstr(&ops));
    } else {
        str_add(out, str_cstr(&name));
    }
    free(name.s);
    free(ops.s);
}
