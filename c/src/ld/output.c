/* output.c -- linker outputs (spec 5.4): mem, ihex and the map. */
#include <stdlib.h>
#include <string.h>

#include "ld.h"

char *mem_text(const LinkResult *r, long mem_size, char **err)
{
    if (r->image_len && r->image_start != 0) {
        *err = xprintf("a .mem image must start at address 0, this one starts at 0x%04lX", r->image_start);
        return nullptr;
    }
    if (r->image_len > mem_size) {
        *err = xprintf("the image is %ld bytes, the .mem size is %ld (see --mem-size)", r->image_len, mem_size);
        return nullptr;
    }
    Str b = {};
    str_add(&b, "@0000\n");
    for (long i = 0; i < mem_size; i += 4) {
        for (long k = i; k < i + 4 && k < mem_size; k++)
            str_addf(&b, k > i ? " %02X" : "%02X", k < r->image_len ? r->image[k] : 0);
        str_addc(&b, '\n');
    }
    return str_take(&b);
}

char *ihex_text(const LinkResult *r)
{
    Str b = {};
    for (long i = 0; i < r->image_len; i += 16) {
        long n = r->image_len - i < 16 ? r->image_len - i : 16;
        long addr = r->image_start + i;
        uint8_t rec[20] = {(uint8_t)n, (uint8_t)(addr >> 8), (uint8_t)(addr & 0xFF), 0};
        memcpy(rec + 4, r->image + i, (size_t)n);
        unsigned sum = 0;
        str_addc(&b, ':');
        for (long k = 0; k < n + 4; k++) {
            str_addf(&b, "%02X", rec[k]);
            sum += rec[k];
        }
        str_addf(&b, "%02X\n", (unsigned)(-sum & 0xFF));
    }
    str_add(&b, ":00000001FF\n");
    return str_take(&b);
}

static const char *kind_name(LinkedKind k)
{
    return k == LS_EXPORTED ? "exported" : "script";
}

static int by_addr_name(const void *x, const void *y)
{
    const LinkedSymbol *a = x, *b = y;
    if (a->addr != b->addr)
        return a->addr < b->addr ? -1 : 1;
    return strcmp(a->name, b->name);
}

char *map_text(const LinkResult *r, const char *script_path)
{
    Str b = {};
    str_addf(&b, "Linker script: %s\n\nMemory regions\n", script_path);
    str_addf(&b, "  %-12s %-6s %-6s %7s %7s %7s\n", "name", "start", "last", "size", "used", "free");
    for (size_t i = 0; i < r->regions.n; i++) {
        const RegionUse *u = &r->regions.v[i];
        str_add(&b, "  ");
        str_pad(&b, u->name, 12);
        str_addf(&b, " 0x%04lX 0x%04lX %7ld %7ld %7ld\n", u->start, u->start + u->size - 1, u->size, u->used,
                 u->size - u->used);
    }
    long len = r->image_len;
    str_addf(&b, "\nImage\n  0x%04lX .. 0x%04lX, %ld bytes\n", r->image_start,
             r->image_start + (len > 1 ? len : 1) - 1, len);
    str_addf(&b, "\nSections\n  %-6s %-6s %7s  %-20s %s\n", "start", "last", "size", "section", "object");
    for (size_t i = 0; i < r->contribs.n; i++) {
        const Contribution *c = &r->contribs.v[i];
        char *label = c->name[0] ? xprintf("%s:%s", SEC_TYPE_NAMES[c->stype], c->name) : xstrdup(SEC_TYPE_NAMES[c->stype]);
        char *last = c->size ? xprintf("0x%04lX", c->addr + c->size - 1) : xstrdup("-");
        str_addf(&b, "  0x%04lX ", c->addr);
        str_pad(&b, last, 6);
        str_addf(&b, " %7ld  ", c->size);
        str_pad(&b, label, 20);
        str_addf(&b, " %s\n", r->paths[c->obj]);
        free(label);
        free(last);
    }
    str_add(&b, "\nSymbols\n");
    LinkedSymbol *syms = xmalloc(r->symbols.n * sizeof *syms + 1);
    memcpy(syms, r->symbols.v, r->symbols.n * sizeof *syms);
    stable_sort(syms, r->symbols.n, sizeof *syms, by_addr_name);
    for (size_t i = 0; i < r->symbols.n; i++) {
        str_addf(&b, "  0x%04lX  ", syms[i].addr);
        str_pad(&b, syms[i].name, 24);
        str_addc(&b, ' ');
        str_pad(&b, kind_name(syms[i].kind), 8);
        str_addf(&b, " %s\n", syms[i].obj >= 0 ? r->paths[syms[i].obj] : "(script)");
    }
    free(syms);
    return str_take(&b);
}
