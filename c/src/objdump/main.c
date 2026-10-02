/* sra8-objdump -- disassemble objects and images; dump symbols and relocations.
 *
 *   sra8-objdump [-d] [-s] [-t] [-r] [--start ADDR] [--end ADDR] file.o | file.bin | file.mem
 *
 * Disassembly is written in the syntax of the assembler, so it assembles
 * again: addresses and bytes go into ';' comments, and words that are not
 * exactly what the assembler would produce are written as .byte.
 */
#include <errno.h>
#include <stdlib.h>
#include <string.h>

#include "../common/isa.h"
#include "../common/json.h"
#include "../common/obj.h"
#include "../common/util.h"

/* ---- input ------------------------------------------------------------------ */

typedef struct {
    long start;
    uint8_t *data;
    long len;
} Image;

static bool read_mem(const char *text, const char *path, Image *img, char **err)
{
    long lo = -1, hi = -1, addr = 0;
    uint8_t *mem = xcalloc(1, 1L << 17);
    bool *set = xcalloc(1, 1L << 17);
    long line_no = 0;
    for (const char *p = text; *p || line_no == 0;) {
        line_no++;
        const char *nl = strchr(p, '\n');
        size_t len = nl ? (size_t)(nl - p) : strlen(p);
        char *line = xstrndup(p, len);
        char *c = strstr(line, "//");
        if (c)
            *c = '\0';
        for (char *tok = strtok(line, " \t\r\v\f"); tok; tok = strtok(nullptr, " \t\r\v\f")) {
            char *end;
            long v = strtol(tok[0] == '@' ? tok + 1 : tok, &end, 16);
            if (*end || end == (tok[0] == '@' ? tok + 1 : tok) || v < 0) {
                *err = xprintf("%s:%ld: bad byte '%s'", path, line_no, tok);
                free(line);
                return false;
            }
            if (tok[0] == '@') {
                addr = v;
                continue;
            }
            if (addr < (1L << 17)) {
                mem[addr] = (uint8_t)(v & 0xFF);
                set[addr] = true;
                if (lo < 0 || addr < lo)
                    lo = addr;
                if (addr > hi)
                    hi = addr;
            }
            addr++;
        }
        free(line);
        if (!nl)
            break;
        p = nl + 1;
    }
    if (lo < 0) {
        *img = (Image){0, xmalloc(1), 0};
    } else {
        *img = (Image){lo, xmalloc((size_t)(hi - lo + 1)), hi - lo + 1};
        memcpy(img->data, mem + lo, (size_t)(hi - lo + 1));
    }
    free(mem);
    free(set);
    return true;
}

/* -> 1 object, 0 image, -1 error */
static int load(const char *path, Object *o, Image *img, char **err)
{
    size_t len;
    char *raw = read_file(path, &len);
    if (!raw) {
        *err = xprintf("cannot read '%s': %s", path, strerror(errno));
        return -1;
    }
    size_t i = 0;
    while (i < len && (raw[i] == ' ' || (raw[i] >= '\t' && raw[i] <= '\r')))
        i++;
    char head = i < len ? raw[i] : '\0';
    if (head == '{' && strlen(raw) == len) {
        char *perr = nullptr;
        Json *j = json_parse(raw, &perr);
        const Json *fmt = json_get(j, "format");
        bool is_obj = fmt && fmt->type == J_STR && strcmp(fmt->s, "sra8-obj") == 0;
        json_free(j);
        free(perr);
        if (is_obj) {
            bool ok = obj_from_json(raw, path, o, err);
            free(raw);
            return ok ? 1 : -1;
        }
    }
    if (ends_with(path, ".mem") || head == '@') {
        bool ok = read_mem(raw, path, img, err);
        free(raw);
        return ok ? 0 : -1;
    }
    *img = (Image){0, (uint8_t *)raw, (long)len};
    return 0;
}

/* ---- disassembly ------------------------------------------------------------- */

static void line_out(Str *b, const char *text, long addr, const uint8_t *data, long n)
{
    str_add(b, "        ");
    str_pad(b, text, 34);
    str_addf(b, " ; %04lX  ", addr);
    for (long i = 0; i < n; i++)
        str_addf(b, i ? " %02X" : "%02X", data[i]);
    str_addc(b, '\n');
}

static char *bytes_directive(const uint8_t *data, long n)
{
    Str b = {};
    str_add(&b, ".byte   ");
    for (long i = 0; i < n; i++)
        str_addf(&b, i ? ", 0x%02X" : "0x%02X", data[i]);
    return str_take(&b);
}

static char *disassemble_image(const Image *img, long lo, long hi)
{
    long start = img->start;
    lo = lo < 0 ? start : (lo > start ? lo : start);
    hi = hi < 0 ? start + img->len : (hi < start + img->len ? hi : start + img->len);
    Str b = {};
    str_addf(&b, "; disassembly of 0x%04lX .. 0x%04lX\n\n.code\n", lo, hi - 1 > lo ? hi - 1 : lo);
    for (long a = lo; a < hi;) {
        const uint8_t *p = img->data + (a - start);
        if ((a - start) % ISA_INSTR_SIZE == 0 && a + ISA_INSTR_SIZE <= hi) {
            Decoded d;
            if (isa_decode(p, &d)) {
                Str t = {};
                isa_text(&d, nullptr, &t);
                line_out(&b, str_cstr(&t), a, p, 4);
                free(t.s);
            } else {
                char *t = bytes_directive(p, 4);
                char *u = xprintf("%s  ; not an instruction", t);
                line_out(&b, u, a, p, 4);
                free(t);
                free(u);
            }
            a += ISA_INSTR_SIZE;
        } else {
            long n = ISA_INSTR_SIZE - (a - start) % ISA_INSTR_SIZE;
            if (hi - a < n)
                n = hi - a;
            char *t = bytes_directive(p, n);
            line_out(&b, t, a, p, n);
            free(t);
            a += n;
        }
    }
    return str_take(&b);
}

/* Labels of an object.  Only exported labels have names in the object;
 * every other address is "section + index", and such targets get the
 * generated names L<section>_<offset> at the nearest place inside the
 * section. */
typedef struct {
    int section;
    long offset;
    StrList names;
} LabelSet;

typedef struct {
    const Object *o;
    VEC(LabelSet) labels;
} Printer;

static LabelSet *label_set(Printer *p, int section, long offset, bool create)
{
    for (size_t i = 0; i < p->labels.n; i++)
        if (p->labels.v[i].section == section && p->labels.v[i].offset == offset)
            return &p->labels.v[i];
    if (!create)
        return nullptr;
    vec_push(p->labels, ((LabelSet){section, offset, {}}));
    return &p->labels.v[p->labels.n - 1];
}

/* A label position for a section relocation: its index, kept inside the section. */
static long anchor(const Printer *p, const Reloc *r)
{
    long size = p->o->sections.v[r->target].size;
    return r->index < 0 ? 0 : r->index > size ? size : r->index;
}

static const Reloc *reloc_at(const Object *o, int section, long offset)
{
    const Reloc *found = nullptr;
    for (size_t i = 0; i < o->relocs.n; i++)
        if (o->relocs.v[i].section == section && o->relocs.v[i].offset == offset)
            found = &o->relocs.v[i];
    return found;
}

static char *ref_text(Printer *p, const Reloc *r)
{
    const char *name;
    long addend;
    if (r->symbol) {
        name = r->symbol;
        addend = r->addend;
    } else {
        long at = anchor(p, r);
        name = label_set(p, r->target, at, false)->names.v[0];
        addend = r->index - at;
    }
    if (addend > 0)
        return xprintf("=%s + %ld", name, addend);
    if (addend < 0)
        return xprintf("=%s - %ld", name, -addend);
    return xprintf("=%s", name);
}

static int cmp_long(const void *x, const void *y)
{
    long a = *(const long *)x, b = *(const long *)y;
    return a < b ? -1 : a > b;
}

static void print_labels(Printer *p, Str *b, int idx, long off)
{
    LabelSet *ls = label_set(p, idx, off, false);
    for (size_t i = 0; ls && i < ls->names.n; i++)
        str_addf(b, "%s:\n", ls->names.v[i]);
}

static void print_section(Printer *p, Str *b, int idx)
{
    const Object *o = p->o;
    const Section *s = &o->sections.v[idx];
    str_addf(b, "\n.%s%s%s\n", SEC_TYPE_NAMES[s->type], s->name[0] ? " " : "", s->name);
    VEC(long) breaks = {};
    for (size_t i = 0; i < p->labels.n; i++)
        if (p->labels.v[i].section == idx)
            vec_push(breaks, p->labels.v[i].offset);
    qsort(breaks.v, breaks.n, sizeof(long), cmp_long);
    if (!s->data) {
        long pos = 0;
        bool end_seen = false;
        for (size_t i = 0; i <= breaks.n; i++) {
            long off = i < breaks.n ? breaks.v[i] : s->size;
            if (i == breaks.n && end_seen)
                break;
            if (off == s->size)
                end_seen = true;
            if (off > pos) {
                str_addf(b, "        .res    %ld\n", off - pos);
                pos = off;
            }
            print_labels(p, b, idx, off);
        }
        free(breaks.v);
        return;
    }
    const uint8_t *data = s->data;
    long size = s->size;
    for (long pos = 0; pos <= size;) {
        print_labels(p, b, idx, pos);
        if (pos == size)
            break;
        long nxt = size;
        for (size_t i = 0; i < breaks.n; i++)
            if (breaks.v[i] > pos && breaks.v[i] < nxt)
                nxt = breaks.v[i];
        const Reloc *r = reloc_at(o, idx, pos);
        bool inside = false;
        for (size_t i = 0; i < o->relocs.n; i++) {
            const Reloc *q = &o->relocs.v[i];
            if (q->section == idx && q->offset >= pos && q->offset < pos + 4 && !(q->offset == pos && q->type == R_IMM16))
                inside = true;
        }
        if (s->type == SEC_CODE && pos % 4 == 0 && pos + 4 <= nxt && !inside) {
            Decoded d;
            if (isa_decode(data + pos, &d)) {
                char *imm = r && r->type == R_IMM16 ? ref_text(p, r) : nullptr;
                Str t = {};
                isa_text(&d, imm, &t);
                line_out(b, str_cstr(&t), pos, data + pos, 4);
                free(t.s);
                free(imm);
                pos += 4;
                continue;
            }
        }
        if (r && r->type == R_ABS16) {
            char *ref = ref_text(p, r);
            char *t = xprintf(".addr   %s", ref);
            line_out(b, t, pos, data + pos, 2);
            free(ref);
            free(t);
            pos += 2;
            continue;
        }
        long end = nxt < pos + 8 ? nxt : pos + 8;
        for (size_t i = 0; i < o->relocs.n; i++) {
            const Reloc *q = &o->relocs.v[i];
            if (q->section == idx && q->offset > pos && q->offset < end)
                end = q->offset;
        }
        if (s->type == SEC_CODE && (pos / 4 + 1) * 4 < end)
            end = (pos / 4 + 1) * 4;
        char *t = bytes_directive(data + pos, end - pos);
        line_out(b, t, pos, data + pos, end - pos);
        free(t);
        pos = end;
    }
    free(breaks.v);
}

static char *disassemble_object(const Object *o)
{
    Printer p = {.o = o};
    for (size_t i = 0; i < o->exports.n; i++) {
        const Export *x = &o->exports.v[i];
        vec_push(label_set(&p, x->section, x->offset, true)->names, xstrdup(x->name));
    }
    for (size_t i = 0; i < o->relocs.n; i++) {
        const Reloc *r = &o->relocs.v[i];
        if (r->symbol)
            continue;
        long at = anchor(&p, r);
        if (label_set(&p, r->target, at, false))
            continue;
        vec_push(label_set(&p, r->target, at, true)->names, xprintf("L%d_%04lX", r->target, at));
    }
    Str b = {};
    str_addf(&b, "; disassembly of %s\n", o->source);
    StrList imports = {};
    obj_imports(o, &imports);
    if (imports.n) {
        str_add(&b, ".import ");
        for (size_t i = 0; i < imports.n; i++)
            str_addf(&b, i ? ", %s" : "%s", imports.v[i]);
        str_addc(&b, '\n');
    }
    strlist_free(&imports);
    for (size_t i = 0; i < o->exports.n; i++)
        str_addf(&b, i ? ", %s" : ".export %s", o->exports.v[i].name);
    if (o->exports.n)
        str_addc(&b, '\n');
    for (size_t i = 0; i < o->sections.n; i++)
        print_section(&p, &b, (int)i);
    return str_take(&b);
}

/* ---- dumps ----------------------------------------------------------------------- */

static char *hexdump(long start, const uint8_t *data, long n, const char *title)
{
    Str b = {};
    str_addf(&b, "%s\n", title);
    for (long i = 0; i < n; i += 16) {
        Str hex = {};
        Str txt = {};
        for (long k = i; k < n && k < i + 16; k++) {
            str_addf(&hex, k > i ? " %02X" : "%02X", data[k]);
            str_addc(&txt, data[k] >= 32 && data[k] < 127 ? (char)data[k] : '.');
        }
        str_addf(&b, "  %04lX  ", start + i);
        str_pad(&b, str_cstr(&hex), 48);
        str_addf(&b, " %s\n", str_cstr(&txt));
        free(hex.s);
        free(txt.s);
    }
    return str_take(&b);
}

static void place(Str *b, const Object *o, int sec, long offset)
{
    char *l = section_label(&o->sections.v[sec]);
    char *p = xprintf("%s+%04lX", l, offset);
    str_pad(b, p, 16);
    free(l);
    free(p);
}

static char *symbols_text(const Object *o)
{
    Str b = {};
    str_add(&b, "sections\n");
    for (size_t i = 0; i < o->sections.n; i++) {
        char *l = section_label(&o->sections.v[i]);
        str_addf(&b, "  [%zu] ", i);
        str_pad(&b, l, 16);
        str_addf(&b, " %5ld bytes\n", o->sections.v[i].size);
        free(l);
    }
    str_add(&b, "\nexports\n");
    for (size_t i = 0; i < o->exports.n; i++) {
        const Export *e = &o->exports.v[i];
        str_add(&b, "  ");
        place(&b, o, e->section, e->offset);
        str_addf(&b, " %s\n", e->name);
    }
    str_add(&b, "\nimports\n");
    StrList imports = {};
    obj_imports(o, &imports);
    for (size_t i = 0; i < imports.n; i++)
        str_addf(&b, "  %s\n", imports.v[i]);
    strlist_free(&imports);
    return str_take(&b);
}

static char *relocs_text(const Object *o)
{
    Str b = {};
    str_add(&b, "relocations\n");
    for (size_t i = 0; i < o->relocs.n; i++) {
        const Reloc *r = &o->relocs.v[i];
        char *source;
        if (r->symbol) {
            source = xprintf("%s %+ld", r->symbol, r->addend);
        } else {
            char *l = section_label(&o->sections.v[r->target]);
            source = xprintf("[%s] %+ld", l, r->index);
            free(l);
        }
        str_add(&b, "  ");
        place(&b, o, r->section, r->offset);
        str_addc(&b, ' ');
        str_pad(&b, REL_TYPE_NAMES[r->type], 6);
        str_addf(&b, " %s\n", source);
        free(source);
    }
    return str_take(&b);
}

/* ---- main ----------------------------------------------------------------------- */

static void usage(FILE *f)
{
    fputs("usage: sra8-objdump [-h] [-d] [-s] [-t] [-r] [--start START] [--end END] file\n", f);
}

[[noreturn]] static void bad_args(const char *msg)
{
    usage(stderr);
    fprintf(stderr, "sra8-objdump: error: %s\n", msg);
    exit(2);
}

static long addr_arg(int argc, char **argv, int *i, const char *name)
{
    const char *a = argv[*i], *v;
    size_t n = strlen(name);
    if (a[n] == '=') {
        v = a + n + 1;
    } else {
        if (++*i >= argc) {
            char *m = xprintf("argument %s: expected one argument", name);
            bad_args(m);
        }
        v = argv[*i];
    }
    long long x;
    if (!parse_int_auto(v, &x)) {
        char *m = xprintf("argument %s: invalid value: '%s'", name, v);
        bad_args(m);
    }
    return (long)x;
}

int main(int argc, char **argv)
{
    bool dis = false, hex = false, syms = false, rel = false;
    long start = -1, end = -1;
    const char *file = nullptr;
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (strcmp(a, "-h") == 0 || strcmp(a, "--help") == 0) {
            usage(stdout);
            fputs("\nSRA-8 object and image dumper\n\n"
                  "positional arguments:\n"
                  "  file               .o object, .bin or .mem image\n\n"
                  "options:\n"
                  "  -h, --help         show this help message and exit\n"
                  "  -d, --disassemble\n"
                  "  -s, --hex          hex dump\n"
                  "  -t, --symbols      sections, exports, imports\n"
                  "  -r, --relocs\n"
                  "  --start START      first address (images)\n"
                  "  --end END          address after the last one (images)\n",
                  stdout);
            return 0;
        }
        if (a[0] == '-' && a[1] && a[1] != '-') {
            for (const char *f = a + 1; *f; f++) {
                if (*f == 'd')
                    dis = true;
                else if (*f == 's')
                    hex = true;
                else if (*f == 't')
                    syms = true;
                else if (*f == 'r')
                    rel = true;
                else {
                    char *m = xprintf("unrecognized arguments: %s", a);
                    bad_args(m);
                }
            }
        } else if (strcmp(a, "--disassemble") == 0) {
            dis = true;
        } else if (strcmp(a, "--hex") == 0) {
            hex = true;
        } else if (strcmp(a, "--symbols") == 0) {
            syms = true;
        } else if (strcmp(a, "--relocs") == 0) {
            rel = true;
        } else if (strncmp(a, "--start", 7) == 0 && (a[7] == '\0' || a[7] == '=')) {
            start = addr_arg(argc, argv, &i, "--start");
        } else if (strncmp(a, "--end", 5) == 0 && (a[5] == '\0' || a[5] == '=')) {
            end = addr_arg(argc, argv, &i, "--end");
        } else if (a[0] == '-' && a[1]) {
            char *m = xprintf("unrecognized arguments: %s", a);
            bad_args(m);
        } else if (!file) {
            file = a;
        } else {
            char *m = xprintf("unrecognized arguments: %s", a);
            bad_args(m);
        }
    }
    if (!file)
        bad_args("the following arguments are required: file");
    if (!(dis || hex || syms || rel))
        dis = true;

    Object o;
    Image img;
    char *err = nullptr;
    int kind = load(file, &o, &img, &err);
    if (kind < 0) {
        fprintf(stderr, "error: %s\n", err);
        return 1;
    }
    VEC(char *) parts = {};
    if (kind == 1) {
        if (syms)
            vec_push(parts, symbols_text(&o));
        if (rel)
            vec_push(parts, relocs_text(&o));
        if (hex)
            for (size_t i = 0; i < o.sections.n; i++)
                if (o.sections.v[i].data) {
                    char *l = section_label(&o.sections.v[i]);
                    char *t = xprintf("section %s", l);
                    vec_push(parts, hexdump(0, o.sections.v[i].data, o.sections.v[i].size, t));
                    free(l);
                    free(t);
                }
        if (dis)
            vec_push(parts, disassemble_object(&o));
    } else {
        if (syms || rel)
            fputs("note: an image has no symbols or relocations\n", stderr);
        if (hex)
            vec_push(parts, hexdump(img.start, img.data, img.len, "image"));
        if (dis)
            vec_push(parts, disassemble_image(&img, start, end));
    }
    for (size_t i = 0; i < parts.n; i++) {
        if (i)
            fputc('\n', stdout);
        fputs(parts.v[i], stdout);
        free(parts.v[i]);
    }
    free(parts.v);
    return 0;
}
