/* assembler.c -- two passes: source lines -> relocatable object (spec 3).
 *
 * Pass 1 parses every statement, assigns section offsets and collects
 * labels, imports and exports.  Pass 2 encodes instructions and data and
 * turns every label reference into a relocation, because addresses exist
 * only after linking: a label of this file becomes "section + index", an
 * imported name stays a name.  Only exported labels go into the object;
 * the rest, and the source lines, are kept for the listing.
 */
#include <stdlib.h>
#include <string.h>

#include "asm.h"

enum { MAX_ERRORS = 20 };

typedef enum { I_INSTR, I_DATA, I_RES } ItemKind;

typedef struct {
    int width;
    Operand v;
} DataValue;

typedef struct {
    ItemKind kind;
    char *where;
    char *path;
    long line;
    int section;
    long offset;
    long size;
    char *text;
    long order;
    const Instr *ins;
    int cond;
    Operand ops[3];
    int nops;
    VEC(DataValue) values;
    Str raw;
} Item;

typedef struct {
    char *name;
    int section;
    long offset;
    char *where;
} Label;

typedef struct {
    char *name;
    long order;
    int section;
    long offset;
} LocalLabel;

typedef struct {
    char *name;
    char *where;
} Named;

typedef struct {
    Object obj;
    int cur;
    VEC(Item) items;
    VEC(Label) labels;
    VEC(LocalLabel) locals;
    VEC(Named) imports;
    VEC(Named) exports;
    StrList used_imports;
    VEC(ListLine) lines;
    StrList errors;
    StrList warnings;
    bool stop;
} Asm;

static const struct {
    const char *name, *hint;
} REMOVED[] = {
    {".org", "placement is done by the linker script"},
    {".align", "placement is done by the linker script"},
    {".balign", "placement is done by the linker script"},
    {".global", "use .export"},
    {".globl", "use .export"},
    {".extern", "use .import"},
    {".weak", "weak symbols do not exist"},
    {".equ", "use !DEFINE for named constants"},
    {".set", "use !DEFINE for named constants"},
    {".section", "use .code, .data or .bss with an optional name"},
    {".text", "use .code"},
    {".rodata", "use .data with a name, e.g. '.data rodata'"},
    {".incbin", "not supported"},
    {".fill", "use .res in .code or .data for zero bytes"},
    {".space", "use .res"},
};

static const char *const NOT_INSTRUCTIONS[] = {"movs", "mvn", "mvns", "nop", "ret", "call", "halt", "push", "pop", "jmp"};

/* ---- helpers ------------------------------------------------------------- */

static const Label *find_label(const Asm *a, const char *name)
{
    for (size_t i = 0; i < a->labels.n; i++)
        if (strcmp(a->labels.v[i].name, name) == 0)
            return &a->labels.v[i];
    return nullptr;
}

static const Named *find_named(const void *vec_v, size_t n, const char *name)
{
    const Named *v = vec_v;
    for (size_t i = 0; i < n; i++)
        if (strcmp(v[i].name, name) == 0)
            return &v[i];
    return nullptr;
}

static bool has_local(const Asm *a, const char *name)
{
    for (size_t i = 0; i < a->locals.n; i++)
        if (strcmp(a->locals.v[i].name, name) == 0)
            return true;
    return false;
}

static void error(Asm *a, AsmErr *e, const char *where)
{
    asm_err_locate(e, where);
    vec_push(a->errors, asm_err_str(e));
    asm_err_free(e);
    if (a->errors.n >= MAX_ERRORS)
        a->stop = true;
}

static int section_index(Asm *a, SecType type, const char *name)
{
    for (size_t i = 0; i < a->obj.sections.n; i++)
        if (a->obj.sections.v[i].type == type && strcmp(a->obj.sections.v[i].name, name) == 0)
            return (int)i;
    vec_push(a->obj.sections, ((Section){.type = type, .name = xstrdup(name)}));
    return (int)a->obj.sections.n - 1;
}

/* The current section.  The unnamed code section that is current before
 * the first section directive is created on first use only. */
static Section *sec(Asm *a)
{
    if (a->cur < 0)
        a->cur = section_index(a, SEC_CODE, "");
    return &a->obj.sections.v[a->cur];
}

static char *label_of(Asm *a, int idx)
{
    return section_label(&a->obj.sections.v[idx]);
}

/* ---- pass 1 ----------------------------------------------------------------- */

static AsmErr *add_item(Asm *a, Item *it)
{
    if (it->offset + it->size > ISA_ADDR_SPACE) {
        char *l = label_of(a, a->cur);
        AsmErr *e = asm_err("section %s grows beyond 64 KiB", l);
        free(l);
        return e;
    }
    sec(a)->size += it->size;
    vec_push(a->items, *it);
    return nullptr;
}

static AsmErr *define_label(Asm *a, const char *name, bool local, long order, const char *where)
{
    long size = sec(a)->size;
    if (local) {
        vec_push(a->locals, ((LocalLabel){xstrdup(name), order, a->cur, size}));
        return nullptr;
    }
    const Label *l = find_label(a, name);
    if (l)
        return asm_err("label '%s' already defined at %s", name, l->where);
    vec_push(a->labels, ((Label){xstrdup(name), a->cur, size, xstrdup(where)}));
    return nullptr;
}

static void free_list(StrList *l)
{
    strlist_free(l);
}

static AsmErr *directive(Asm *a, const char *word, const char *rest, long order, Item *base)
{
    for (size_t i = 0; i < sizeof REMOVED / sizeof REMOVED[0]; i++)
        if (strcmp(word, REMOVED[i].name) == 0)
            return asm_err("'%s' does not exist: %s", word, REMOVED[i].hint);
    static const char *const SECTIONS[] = {".code", ".data", ".bss"};
    for (int t = 0; t < 3; t++) {
        if (strcmp(word, SECTIONS[t]) != 0)
            continue;
        if (rest[0] && !is_ident(rest))
            return asm_err("'%s' takes an optional section name, got '%s'", word, rest);
        a->cur = section_index(a, (SecType)t, rest);
        return nullptr;
    }
    StrList ops = {};
    AsmErr *e = nullptr;
    if (strcmp(word, ".import") == 0 || strcmp(word, ".export") == 0) {
        bool imp = word[1] == 'i';
        if ((e = split_operands(rest, &ops)))
            goto out;
        if (!ops.n) {
            e = asm_err("'%s' needs at least one name", word);
            goto out;
        }
        for (size_t i = 0; i < ops.n; i++) {
            const char *n = ops.v[i];
            if (!is_ident(n)) {
                e = asm_err("bad name '%s'", n);
                goto out;
            }
            bool dup = imp ? find_named(a->imports.v, a->imports.n, n) : find_named(a->exports.v, a->exports.n, n);
            if (dup)
                vec_push(a->warnings, xprintf("%s: '%s' is already %sed", base->where, n, word + 1));
            else if (imp)
                vec_push(a->imports, ((Named){xstrdup(n), xstrdup(base->where)}));
            else
                vec_push(a->exports, ((Named){xstrdup(n), xstrdup(base->where)}));
        }
        goto out;
    }
    if ((e = split_operands(rest, &ops)))
        goto out;
    SecType stype = sec(a)->type;
    Item it = *base;
    it.section = a->cur;
    it.offset = sec(a)->size;
    it.order = order;
    if (strcmp(word, ".res") == 0) {
        if (ops.n != 1) {
            e = asm_err("'.res' takes 1 operand, got %zu", ops.n);
            goto out;
        }
        Operand v;
        if ((e = parse_value(ops.v[0], &v)))
            goto out;
        if (v.kind != OP_IMM || v.value < 0 || v.value > ISA_ADDR_SPACE) {
            free(v.kind == OP_LABEL ? v.name : nullptr);
            e = asm_err("'.res' needs a size 0 .. 65536");
            goto out;
        }
        it.kind = I_RES;
        it.size = (long)v.value;
        e = add_item(a, &it);
        goto out;
    }
    if (stype == SEC_BSS) {
        e = asm_err("only .res is allowed in a .bss section");
        goto out;
    }
    it.kind = I_DATA;
    static const struct {
        const char *name;
        int width;
    } WIDTHS[] = {{".byte", 1}, {".word", 1}, {".dword", 2}, {".qword", 4}, {".addr", 2}};
    int width = 0;
    for (size_t i = 0; i < sizeof WIDTHS / sizeof WIDTHS[0]; i++)
        if (strcmp(word, WIDTHS[i].name) == 0)
            width = WIDTHS[i].width;
    if (width) {
        if (!ops.n) {
            e = asm_err("'%s' needs at least one value", word);
            goto out;
        }
        for (size_t i = 0; i < ops.n; i++) {
            Operand v;
            if ((e = parse_value(ops.v[i], &v)))
                goto out;
            if (v.kind == OP_LABEL && strcmp(word, ".addr") != 0) {
                free(v.name);
                e = asm_err("label reference not allowed in '%s', use .addr", word);
                goto out;
            }
            vec_push(it.values, ((DataValue){width, v}));
        }
        it.size = width * (long)ops.n;
    } else if (strcmp(word, ".ascii") == 0 || strcmp(word, ".asciz") == 0) {
        if (ops.n != 1) {
            e = asm_err("'%s' takes 1 operand, got %zu", word, ops.n);
            goto out;
        }
        const char *s = ops.v[0];
        size_t n = strlen(s);
        if (n < 2 || s[0] != '"' || s[n - 1] != '"') {
            e = asm_err("'%s' needs a \"string\"", word);
            goto out;
        }
        if ((e = unescape(s + 1, n - 2, &it.raw)))
            goto out;
        if (word[5] == 'z')
            str_addn(&it.raw, "", 1);
        it.size = (long)it.raw.len;
    } else {
        e = asm_err("unknown directive '%s'", word);
        goto out;
    }
    e = add_item(a, &it);
out:
    free_list(&ops);
    return e;
}

static AsmErr *check_operands(Asm *a, Item *it)
{
    const Format *f = it->ins->fmt;
    int widths[3], n = 0;
    for (int i = 0; i < f->nregs; i++)
        widths[n++] = f->regs[i];
    if (f->src)
        widths[n++] = f->src;
    for (int i = 0; i < n; i++) {
        const Operand *op = &it->ops[i];
        int bits = widths[i];
        bool is_src = f->src && i == n - 1;
        if (op->kind == OP_REG) {
            if (op->pair != (bits == 16)) {
                char *want = bits == 16 ? xprintf("a 16 bit register pair (r%da)", op->n)
                                        : xprintf("an 8 bit register (r%d)", op->n);
                AsmErr *e = asm_err("operand %d of '%s' must be %s, got 'r%d%s'", i + 1, it->ins->mnemonic, want,
                                    op->n, op->pair ? "a" : "");
                free(want);
                return e;
            }
            if (op->pair && op->n == 15)
                vec_push(a->warnings, xprintf("%s: r15a has no high register, the high byte wraps to r0", it->where));
        } else if (!is_src) {
            return asm_err("operand %d of '%s' must be a register", i + 1, it->ins->mnemonic);
        } else if (op->kind == OP_LABEL && bits != 16) {
            return asm_err("'%s' takes an 8 bit immediate, a label reference is not allowed", it->ins->mnemonic);
        } else if (op->kind == OP_IMM) {
            long long field;
            if (!isa_fit(op->value, bits, &field))
                return asm_err("value %lld does not fit in %d bits", op->value, bits);
        }
    }
    return nullptr;
}

static AsmErr *instruction(Asm *a, const char *word, const char *rest, long order, Item *base)
{
    char *lower = xstrdup(word);
    for (char *p = lower; *p; p++)
        if (*p >= 'A' && *p <= 'Z')
            *p = (char)(*p + 32);
    char *dot = strchr(lower, '.');
    const char *cond = dot ? dot + 1 : nullptr;
    if (dot)
        *dot = '\0';
    AsmErr *e = nullptr;
    StrList ops = {};
    const Instr *ins = isa_find(lower);
    if (!ins) {
        bool pseudo = false;
        for (size_t i = 0; i < sizeof NOT_INSTRUCTIONS / sizeof NOT_INSTRUCTIONS[0]; i++)
            pseudo |= strcmp(lower, NOT_INSTRUCTIONS[i]) == 0;
        e = pseudo ? asm_err("'%s' is not an SRA-8 instruction (there are no pseudo-instructions)", lower)
                   : asm_err("unknown instruction '%s'", word);
        goto out;
    }
    if (cond && isa_cond(cond) < 0) {
        e = asm_err("unknown condition '%s'", cond);
        goto out;
    }
    Section *s = sec(a);
    if (s->type != SEC_CODE) {
        e = asm_err("instruction in a .%s section", SEC_TYPE_NAMES[s->type]);
        goto out;
    }
    if (s->size % ISA_INSTR_SIZE) {
        char *l = label_of(a, a->cur);
        e = asm_err("instruction at unaligned offset %ld of section %s; pad the preceding data "
                    "to a multiple of 4 bytes or move it to a .data section", s->size, l);
        free(l);
        goto out;
    }
    if ((e = split_operands(rest, &ops)))
        goto out;
    Item it = *base;
    it.kind = I_INSTR;
    it.section = a->cur;
    it.offset = s->size;
    it.size = ISA_INSTR_SIZE;
    it.order = order;
    it.ins = ins;
    it.cond = cond ? isa_cond(cond) : 0;
    for (size_t i = 0; i < ops.n; i++) {
        Operand op;
        if ((e = parse_operand(ops.v[i], &op)))
            goto out;
        if (i < 3)
            it.ops[i] = op;
    }
    int want = fmt_operands(ins->fmt);
    if ((int)ops.n != want) {
        e = asm_err("'%s' takes %d operand%s, got %zu", ins->mnemonic, want, want == 1 ? "" : "s", ops.n);
        goto out;
    }
    it.nops = want;
    if ((e = check_operands(a, &it)))
        goto out;
    e = add_item(a, &it);
out:
    free_list(&ops);
    free(lower);
    return e;
}

static AsmErr *statement(Asm *a, const SrcLine *src, long order, const char *where)
{
    const char *text = src->text;
    for (;;) {
        /* (\.l\s+)?(IDENT)\s*:\s* */
        const char *p = text;
        bool local = false;
        if (p[0] == '.' && p[1] == 'l' && py_space((unsigned char)p[2])) {
            local = true;
            p += 2;
            while (py_space((unsigned char)*p))
                p++;
        }
        size_t n = match_ident(p);
        const char *q = p + n;
        while (n && py_space((unsigned char)*q))
            q++;
        if (!n || *q != ':')
            break;
        char *name = xstrndup(p, n);
        AsmErr *e = define_label(a, name, local, order, where);
        free(name);
        if (e)
            return e;
        q++;
        while (py_space((unsigned char)*q))
            q++;
        text = q;
    }
    if (!*text)
        return nullptr;
    const char *w = text;
    while (*w && !py_space((unsigned char)*w))
        w++;
    char *word = xstrndup(text, (size_t)(w - text));
    char *rest = strip_copy(w, strlen(w));
    Item base = {.where = xstrdup(where), .path = src->path, .line = src->line, .text = xstrdup(text)};
    AsmErr *e = word[0] == '.' ? directive(a, word, rest, order, &base) : instruction(a, word, rest, order, &base);
    free(word);
    free(rest);
    return e;
}

/* ---- pass 2 ----------------------------------------------------------------- */

static void check_linkage(Asm *a)
{
    for (size_t i = 0; i < a->imports.n; i++)
        if (find_label(a, a->imports.v[i].name))
            vec_push(a->errors, xprintf("%s: '%s' is imported but also defined in this file", a->imports.v[i].where,
                                        a->imports.v[i].name));
    for (size_t i = 0; i < a->exports.n; i++) {
        const Named *x = &a->exports.v[i];
        if (find_named(a->imports.v, a->imports.n, x->name))
            vec_push(a->errors, xprintf("%s: '%s' is imported, it cannot be exported", x->where, x->name));
        else if (!find_label(a, x->name))
            vec_push(a->errors, xprintf("%s: exported label '%s' is not defined%s", x->where, x->name,
                                        has_local(a, x->name) ? " (local labels cannot be exported)" : ""));
    }
}

/* -> an imported name and its addend, or a section of this file and the index */
static AsmErr *resolve(Asm *a, const Operand *ref, const Item *it, char **symbol, int *target, long *value)
{
    if (!ref->dir) {
        const Label *l = find_label(a, ref->name);
        if (l) {
            *symbol = nullptr;
            *target = l->section;
            *value = l->offset + (long)ref->offset;
            return nullptr;
        }
        if (find_named(a->imports.v, a->imports.n, ref->name)) {
            if (!strlist_has(&a->used_imports, ref->name))
                vec_push(a->used_imports, xstrdup(ref->name));
            *symbol = xstrdup(ref->name);
            *target = -1;
            *value = (long)ref->offset;
            return nullptr;
        }
        if (has_local(a, ref->name))
            return asm_err("undefined label '%s' (a local label: use .b =%s or .f =%s)", ref->name, ref->name, ref->name);
        return asm_err("undefined name '%s' (add '.import %s' if it is defined in another file)", ref->name, ref->name);
    }
    const LocalLabel *pick = nullptr;
    for (size_t i = 0; i < a->locals.n; i++) {
        const LocalLabel *l = &a->locals.v[i];
        if (strcmp(l->name, ref->name) != 0)
            continue;
        if (ref->dir == 'b' && l->order <= it->order)
            pick = l;
        if (ref->dir == 'f' && l->order > it->order && !pick)
            pick = l;
    }
    if (!pick)
        return asm_err("no local label '%s' %s this line", ref->name, ref->dir == 'b' ? "before" : "after");
    *symbol = nullptr;
    *target = pick->section;
    *value = pick->offset + (long)ref->offset;
    return nullptr;
}

static AsmErr *add_reloc(Asm *a, const Item *it, long at, RelType type, const Operand *ref, long long *field)
{
    char *symbol = nullptr;
    int target = -1;
    long value = 0;
    AsmErr *e = resolve(a, ref, it, &symbol, &target, &value);
    if (e)
        return e;
    if (symbol)
        vec_push(a->obj.relocs, ((Reloc){.section = it->section, .offset = at, .type = type, .target = -1,
                                         .symbol = symbol, .addend = value}));
    else
        vec_push(a->obj.relocs, ((Reloc){.section = it->section, .offset = at, .type = type, .target = target,
                                         .index = value}));
    *field = value & 0xFFFF;    /* the field holds the index or addend until linking */
    return nullptr;
}

static AsmErr *encode_instr(Asm *a, const Item *it, uint8_t out[4])
{
    const Instr *ins = it->ins;
    int opcode = ins->opcode, args[3] = {};
    long long imm = 0;
    int n = fmt_operands(ins->fmt);
    for (int i = 0; i < it->nops; i++) {
        const Operand *op = &it->ops[i];
        bool is_src = ins->fmt->src && i == n - 1;
        if (op->kind == OP_REG) {
            args[i] = op->n;
        } else if (op->kind == OP_IMM) {
            opcode |= 1;
            if (!isa_fit(op->value, ins->fmt->src, &imm))
                return asm_err("value %lld does not fit in %d bits", op->value, ins->fmt->src);
        } else if (is_src) {
            opcode |= 1;
            AsmErr *e = add_reloc(a, it, it->offset, R_IMM16, op, &imm);
            if (e)
                return e;
        }
    }
    isa_encode(out, it->cond, opcode, args, imm);
    return nullptr;
}

static AsmErr *encode_data(Asm *a, const Item *it, Str *out)
{
    if (it->raw.len) {
        str_addn(out, it->raw.s, it->raw.len);
        return nullptr;
    }
    for (size_t i = 0; i < it->values.n; i++) {
        const DataValue *dv = &it->values.v[i];
        long long value;
        if (dv->v.kind == OP_LABEL) {
            AsmErr *e = add_reloc(a, it, it->offset + (long)out->len, R_ABS16, &dv->v, &value);
            if (e)
                return e;
        } else if (!isa_fit(dv->v.value, 8 * dv->width, &value)) {
            return asm_err("value %lld does not fit in %d bits", dv->v.value, 8 * dv->width);
        }
        for (int k = 0; k < dv->width; k++)
            str_addc(out, (char)(value >> (8 * k) & 0xFF));
    }
    return nullptr;
}

static void pass2(Asm *a)
{
    check_linkage(a);
    for (size_t i = 0; i < a->obj.sections.n; i++) {
        Section *s = &a->obj.sections.v[i];
        if (s->type != SEC_BSS) {
            s->data = xcalloc((size_t)s->size + 1, 1);
            s->cap = s->size;
        }
    }
    static const char *const KINDS[] = {"instr", "data", "res"};
    for (size_t i = 0; i < a->items.n && !a->stop; i++) {
        Item *it = &a->items.v[i];
        Str data = {};
        AsmErr *e = nullptr;
        if (it->kind == I_INSTR) {
            uint8_t w[4];
            if (!(e = encode_instr(a, it, w)))
                str_addn(&data, (char *)w, 4);
        } else if (it->kind == I_DATA) {
            e = encode_data(a, it, &data);
        }
        if (e) {
            free(data.s);
            error(a, e, it->where);
            continue;
        }
        Section *s = &a->obj.sections.v[it->section];
        if (s->data && data.len)
            memcpy(s->data + it->offset, data.s, data.len);  /* res items stay zero */
        free(data.s);
        vec_push(a->lines, ((ListLine){it->section, it->offset, it->size, latin1_to_utf8(it->text, strlen(it->text)),
                                       KINDS[it->kind]}));
    }
    if (a->stop)
        return;
    for (size_t i = 0; i < a->imports.n; i++) {
        const Named *n = &a->imports.v[i];
        if (!strlist_has(&a->used_imports, n->name) && !find_label(a, n->name))
            vec_push(a->warnings, xprintf("%s: imported name '%s' is never used", n->where, n->name));
    }
}

static void build(Asm *a, AsmResult *res)
{
    for (size_t i = 0; i < a->labels.n; i++) {
        const Label *l = &a->labels.v[i];
        bool exported = find_named(a->exports.v, a->exports.n, l->name) != nullptr;
        if (exported)
            vec_push(a->obj.exports, ((Export){xstrdup(l->name), l->section, l->offset}));
        vec_push(res->labels, ((ListLabel){l->name, l->section, l->offset, exported}));
    }
}

void assemble(const SrcLines *lines, const char *source, AsmResult *res)
{
    Asm a = {.cur = -1};
    a.obj.source = xstrdup(source);
    for (size_t i = 0; i < lines->n && !a.stop; i++) {
        const SrcLine *l = &lines->v[i];
        char *where = xprintf("%s:%ld", l->path, l->line);
        AsmErr *e = statement(&a, l, (long)i, where);
        if (e)
            error(&a, e, where);
        free(where);
    }
    if (!a.errors.n)
        pass2(&a);
    if (a.stop)
        vec_push(a.errors, xstrdup("too many errors, stopping"));
    if (!a.errors.n)
        build(&a, res);
    res->obj = a.obj;
    res->errors = a.errors;
    res->warnings = a.warnings;
    res->lines.v = a.lines.v;
    res->lines.n = a.lines.n;
    /* the rest of the assembler state lives until the process exits */
}
