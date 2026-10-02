/* listing.c -- the assembler listing (spec 3.9): section-relative offsets.
 * Made from the assembler's state: the object has no source lines and no
 * labels that are not exported. */
#include <stdlib.h>
#include <string.h>

#include "asm.h"

static void place(Str *b, const Object *o, int sec, long offset)
{
    char *l = section_label(&o->sections.v[sec]);
    char *p = xprintf("%s+%04lX", l, offset);
    str_pad(b, p, 16);
    free(l);
    free(p);
}

static int by_section_offset(const void *x, const void *y)
{
    const ListLabel *a = x, *b = y;
    if (a->section != b->section)
        return a->section < b->section ? -1 : 1;
    return a->offset < b->offset ? -1 : a->offset > b->offset;
}

char *asm_listing(const AsmResult *r)
{
    const Object *o = &r->obj;
    Str b = {};
    for (size_t i = 0; i < r->lines.n; i++) {
        const ListLine *l = &r->lines.v[i];
        place(&b, o, l->section, l->offset);
        str_addc(&b, ' ');
        if (strcmp(l->kind, "res") == 0) {
            char *s = xprintf("(%ld bytes)", l->size);
            str_pad(&b, s, 24);
            free(s);
            str_addf(&b, " %s\n", l->text);
            continue;
        }
        const Section *s = &o->sections.v[l->section];
        long n = s->data ? l->size : 0;
        Str hex = {};
        for (long k = 0; k < n && k < 8; k++)
            str_addf(&hex, k ? " %02X" : "%02X", s->data[l->offset + k]);
        str_pad(&b, str_cstr(&hex), 24);
        free(hex.s);
        str_addf(&b, " %s\n", l->text);
        for (long k = 8; k < n; k += 8) {
            place(&b, o, l->section, l->offset + k);
            str_addc(&b, ' ');
            for (long j = k; j < n && j < k + 8; j++)
                str_addf(&b, j > k ? " %02X" : "%02X", s->data[l->offset + j]);
            str_addc(&b, '\n');
        }
    }
    str_add(&b, "\nsections\n");
    for (size_t i = 0; i < o->sections.n; i++) {
        char *l = section_label(&o->sections.v[i]);
        str_add(&b, "  ");
        str_pad(&b, l, 16);
        str_addf(&b, " %5ld bytes\n", o->sections.v[i].size);
        free(l);
    }
    str_add(&b, "\nlabels\n");
    ListLabel *labels = xmalloc(r->labels.n * sizeof *labels + 1);
    memcpy(labels, r->labels.v, r->labels.n * sizeof *labels);
    stable_sort(labels, r->labels.n, sizeof *labels, by_section_offset);
    for (size_t i = 0; i < r->labels.n; i++) {
        str_add(&b, "  ");
        place(&b, o, labels[i].section, labels[i].offset);
        str_addf(&b, " %s%s\n", labels[i].name, labels[i].exported ? "  (exported)" : "");
    }
    free(labels);
    str_add(&b, "\nimports\n");
    StrList imports = {};
    obj_imports(o, &imports);
    for (size_t i = 0; i < imports.n; i++)
        str_addf(&b, "  %s\n", imports.v[i]);
    strlist_free(&imports);
    str_add(&b, "\nrelocations\n");
    for (size_t i = 0; i < o->relocs.n; i++) {
        const Reloc *rl = &o->relocs.v[i];
        char *source;
        long value;
        if (rl->symbol) {
            source = xstrdup(rl->symbol);
            value = rl->addend;
        } else {
            char *l = section_label(&o->sections.v[rl->target]);
            source = xprintf("[%s]", l);
            free(l);
            value = rl->index;
        }
        str_add(&b, "  ");
        place(&b, o, rl->section, rl->offset);
        str_addc(&b, ' ');
        str_pad(&b, REL_TYPE_NAMES[rl->type], 6);
        str_addf(&b, " %s %c 0x%lX\n", source, value >= 0 ? '+' : '-', labs(value));
        free(source);
    }
    return str_take(&b);
}
