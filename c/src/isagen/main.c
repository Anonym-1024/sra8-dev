/* isagen -- everything generated from or checked against the instruction table.
 *
 *   isagen markdown          print docs/isa.md
 *   isagen asm-grammar       print the VS Code grammar of the assembly language
 *   isagen check-rtl DIR     compare the table with control_rom_gen.c and
 *                            control_rom.mem of the RTL folder DIR
 */
#include <errno.h>
#include <stdlib.h>
#include <string.h>

#include "../common/isa.h"
#include "../common/util.h"
#include "grammar_template.inc"

/* ---- markdown ------------------------------------------------------------------ */

static void markdown(void)
{
    Str b = {};
    str_add(&b, "# SRA-8 instruction set\n\n"
                "Generated from the instruction table (`sra8/isa.py`, mirrored by `c/src/common/isa.c`) with `make docs`. Do not edit.\n\n"
                "## Instruction word\n\n"
                "32 bit, stored big-endian (the byte at the lowest address holds bits 31:24).\n\n"
                "| Bits | Field |\n|---|---|\n"
                "| 31:28 | condition |\n| 27 | unused, 0 |\n| 26:20 | opcode; bit 20 = immediate form |\n"
                "| 19:16 | arg1 |\n| 15:12 | arg2 |\n| 11:8 | arg3 |\n"
                "| 7:0 | imm8 |\n| 15:0 | imm16 (overlaps arg2 and arg3) |\n\n"
                "Register operands fill arg1, arg2, arg3 in the order they are written. "
                "`rNa` is the pair r(N+1):rN, low byte in rN; r15a wraps to r0 as the high byte.\n\n"
                "## Operand formats\n\n| Format | Operands |\n|---|---|\n");
    for (size_t i = 0; i < ISA_N_FORMATS; i++)
        str_addf(&b, "| %s | %s |\n", ISA_FORMATS[i].name, ISA_FORMATS[i].syntax[0] ? ISA_FORMATS[i].syntax : "—");
    str_addf(&b, "\n## Conditions\n\n"
                 "Written as a suffix: `add.eq r1, r2, r3`. A false condition costs %d clocks and changes nothing.\n\n"
                 "| Code | Suffix | True when |\n|---|---|---|\n", ISA_SKIPPED_CYCLES);
    for (int i = 0; i < 16; i++)
        str_addf(&b, "| %d | `%s` | %s |\n", i, ISA_CONDITIONS[i].name, ISA_CONDITIONS[i].meaning);
    str_add(&b, "\n## ALU operations\n\nZ = result is 0, N = bit 7 of the result for every operation.\n\n"
                "| Code | Operation | Result | C | V |\n|---|---|---|---|---|\n");
    for (size_t i = 0; i < ISA_N_ALU_OPS; i++) {
        const AluOp *a = &ISA_ALU_OPS[i];
        str_addf(&b, "| %zu | %s | %s | %s | %s |\n", i, a->name, a->result, a->c, a->v);
    }
    str_addf(&b, "\n## Instructions\n\nCycles = %d × (%d fetch steps + steps), at %ld MHz.\n", ISA_CLOCKS_PER_STEP,
             ISA_FETCH_STEPS, ISA_CLOCK_HZ / 1'000'000);
    for (size_t g = 0; g < ISA_N_GROUPS; g++) {
        str_addf(&b, "\n### %s\n\n| Mnemonic | Operands | Reg | Imm | Steps | Cycles | Meaning |\n"
                     "|---|---|---|---|---|---|---|\n", ISA_GROUPS[g]);
        for (size_t i = 0; i < ISA_N_INSTRUCTIONS; i++) {
            const Instr *ins = &ISA_INSTRUCTIONS[i];
            if (strcmp(ins->group, ISA_GROUPS[g]) != 0)
                continue;
            char imm[16] = "—";
            if (ins->fmt->src)
                snprintf(imm, sizeof imm, "%d", ins->opcode | 1);
            str_addf(&b, "| `%s` | %s | %d | %s | %d | %d | %s |\n", ins->mnemonic,
                     ins->fmt->syntax[0] ? ins->fmt->syntax : "—", ins->opcode, imm, ins->steps, isa_cycles(ins),
                     ins->meaning);
        }
    }
    str_add(&b, "\n## Undefined opcodes\n\n");
    bool first = true;
    for (int op = 0; op < 128; op++) {
        bool imm;
        if (isa_opcode(op, &imm))
            continue;
        str_addf(&b, first ? "%d" : ", %d", op);
        first = false;
    }
    str_add(&b, ".\n\nTheir microcode is all zero and never returns to fetch: executing one is destructive. "
                "The assembler cannot produce them.\n");
    fputs(str_cstr(&b), stdout);
    free(b.s);
}

/* ---- VS Code grammar --------------------------------------------------------------- */

static int longest_first(const void *x, const void *y)
{
    const char *a = *(const char *const *)x, *b = *(const char *const *)y;
    size_t la = strlen(a), lb = strlen(b);
    if (la != lb)
        return la > lb ? -1 : 1;
    return strcmp(a, b);
}

static char *alternation(const char **words, size_t n)
{
    qsort(words, n, sizeof *words, longest_first);
    Str b = {};
    for (size_t i = 0; i < n; i++)
        str_addf(&b, i ? "|%s" : "%s", words[i]);
    return str_take(&b);
}

static void asm_grammar(void)
{
    const char *mn[128], *co[16];
    for (size_t i = 0; i < ISA_N_INSTRUCTIONS; i++)
        mn[i] = ISA_INSTRUCTIONS[i].mnemonic;
    for (int i = 0; i < 16; i++)
        co[i] = ISA_CONDITIONS[i].name;
    char *m = alternation(mn, ISA_N_INSTRUCTIONS), *c = alternation(co, 16);
    for (const char *p = GRAMMAR_TEMPLATE; *p;) {
        if (strncmp(p, "@MNEMONICS@", 11) == 0) {
            fputs(m, stdout);
            p += 11;
        } else if (strncmp(p, "@CONDITIONS@", 12) == 0) {
            fputs(c, stdout);
            p += 12;
        } else {
            fputc(*p++, stdout);
        }
    }
    free(m);
    free(c);
}

/* ---- check against the RTL ------------------------------------------------------------ */

static int failures;

static void fail(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    fputs("check-rtl: ", stderr);
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
    va_end(ap);
    failures++;
}

/* OPC_<NAME> = <number> in control_rom_gen.c */
static void check_enum(const char *dir)
{
    char *path = path_join(dir, "control_unit_gen/control_rom_gen.c");
    char *src = read_file(path, nullptr);
    if (!src) {
        fail("cannot read '%s': %s", path, strerror(errno));
        free(path);
        return;
    }
    bool seen[128] = {};
    int count = 0;
    for (const char *p = strstr(src, "OPC_"); p; p = strstr(p + 1, "OPC_")) {
        const char *q = p + 4;
        size_t n = 0;
        while (is_ident_start((unsigned char)q[n]) || (q[n] >= '0' && q[n] <= '9'))
            n++;
        const char *r = q + n;
        while (*r == ' ' || *r == '\t')
            r++;
        if (!n || *r != '=')
            continue;
        r++;
        while (*r == ' ' || *r == '\t')
            r++;
        if (*r < '0' || *r > '9')
            continue;
        int value = atoi(r);
        bool imm = n > 2 && q[n - 2] == '_' && q[n - 1] == 'I';
        char *name = xstrndup(q, imm ? n - 2 : n);
        for (char *s = name; *s; s++)
            if (*s >= 'A' && *s <= 'Z')
                *s = (char)(*s + 32);
        const Instr *ins = isa_find(name);
        count++;
        if (!ins)
            fail("OPC_%.*s: no such instruction in isa.c", (int)n, q);
        else if ((ins->opcode | (imm ? 1 : 0)) != value)
            fail("OPC_%.*s = %d, isa.c says %d", (int)n, q, value, ins->opcode | (imm ? 1 : 0));
        else if (imm && !ins->fmt->src)
            fail("OPC_%.*s: isa.c has no immediate form", (int)n, q);
        if (value >= 0 && value < 128)
            seen[value] = true;
        free(name);
    }
    if (!count)
        fail("no OPC_ values found in '%s'", path);
    for (size_t i = 0; i < ISA_N_INSTRUCTIONS; i++) {
        const Instr *ins = &ISA_INSTRUCTIONS[i];
        if (!seen[ins->opcode])
            fail("%s: opcode %d missing in control_rom_gen.c", ins->mnemonic, ins->opcode);
        if (ins->fmt->src && !seen[ins->opcode | 1])
            fail("%s: immediate form %d missing in control_rom_gen.c", ins->mnemonic, ins->opcode | 1);
    }
    free(src);
    free(path);
}

/* The ucr step (MUX 3 code 5) ends every instruction; undefined opcodes are all zero. */
static void check_rom(const char *dir)
{
    char *path = path_join(dir, "control_rom.mem");
    char *text = read_file(path, nullptr);
    if (!text) {
        fail("cannot read '%s': %s", path, strerror(errno));
        free(path);
        return;
    }
    unsigned rom[1024] = {};
    int n = 0;
    for (char *tok = strtok(text, " \t\r\n"); tok && n < 1024; tok = strtok(nullptr, " \t\r\n"))
        rom[n++] = (unsigned)strtoul(tok, nullptr, 16);
    if (n != 1024)
        fail("%s: %d words, expected 1024", path, n);
    for (int op = 0; op < 128; op++) {
        bool imm;
        const Instr *ins = isa_opcode(op, &imm);
        int ucr = -1, nonzero = 0;
        for (int s = 0; s < 8; s++) {
            nonzero |= rom[op * 8 + s] != 0;
            if (ucr < 0 && (rom[op * 8 + s] >> 4 & 7) == 5)
                ucr = s;
        }
        if (!ins && nonzero)
            fail("opcode %d is undefined in isa.c but has microcode", op);
        if (ins && ucr + 1 != ins->steps)
            fail("%s%s (opcode %d): %d steps in the ROM, isa.c says %d", ins->mnemonic, imm ? " imm" : "", op, ucr + 1,
                 ins->steps);
    }
    free(text);
    free(path);
}

int main(int argc, char **argv)
{
    if (argc == 2 && strcmp(argv[1], "markdown") == 0) {
        markdown();
        return 0;
    }
    if (argc == 2 && strcmp(argv[1], "asm-grammar") == 0) {
        asm_grammar();
        return 0;
    }
    if (argc == 3 && strcmp(argv[1], "check-rtl") == 0) {
        check_enum(argv[2]);
        check_rom(argv[2]);
        if (failures)
            return 1;
        printf("check-rtl: %zu instructions agree with %s\n", ISA_N_INSTRUCTIONS, argv[2]);
        return 0;
    }
    fputs("usage: isagen markdown | asm-grammar | check-rtl RTL_DIR\n", stderr);
    return 2;
}
