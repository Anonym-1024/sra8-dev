/* script.c -- the linker script language (spec 5.2).
 *
 *   memory NAME start ADDR size BYTES
 *   place REGION
 *       code|data|bss [NAME | *]
 *       align N
 *       symbol NAME
 *   end
 *   symbol NAME = NUMBER | start REGION | last REGION
 *
 * ';' starts a comment.  Numbers are decimal, 0x... or 0b....
 */
#include <errno.h>
#include <stdlib.h>
#include <string.h>

#include "ld.h"

static const char *const KEYWORDS[] = {"memory", "start", "size", "place", "end", "align", "symbol", "last",
                                       "code", "data", "bss"};

static int section_type(const char *w)
{
    for (int i = 0; i < 3; i++)
        if (strcmp(w, SEC_TYPE_NAMES[i]) == 0)
            return i;
    return -1;
}

static bool parse_number(const char *text, long *out)
{
    char *t = xstrdup(text);
    for (char *p = t; *p; p++)
        if (*p >= 'A' && *p <= 'Z')
            *p = (char)(*p + 32);
    int base = 10;
    const char *d = t;
    if (t[0] == '0' && t[1] == 'x')
        base = 16, d = t + 2;
    else if (t[0] == '0' && t[1] == 'b')
        base = 2, d = t + 2;
    bool ok = *d != '\0';
    long v = 0;
    for (; *d && ok; d++) {
        int x = *d >= '0' && *d <= '9' ? *d - '0' : *d >= 'a' && *d <= 'f' ? *d - 'a' + 10 : 99;
        if (x >= base || v > (0x7FFFFFFFL - x) / base)
            ok = false;
        else
            v = v * base + x;
    }
    free(t);
    *out = v;
    return ok;
}

static bool check_name(const char *w, const char *where, const char *what, char **err)
{
    bool ok = is_ident(w);
    for (size_t i = 0; ok && i < sizeof KEYWORDS / sizeof KEYWORDS[0]; i++)
        ok = strcmp(w, KEYWORDS[i]) != 0;
    if (!ok)
        *err = xprintf("%s: bad %s name '%s'", where, what, w);
    return ok;
}

const Region *script_region(const Script *s, const char *name)
{
    for (size_t i = 0; i < s->regions.n; i++)
        if (strcmp(s->regions.v[i].name, name) == 0)
            return &s->regions.v[i];
    return nullptr;
}

static bool has_place(const Script *s, const char *region)
{
    for (size_t i = 0; i < s->places.n; i++)
        if (strcmp(s->places.v[i].region, region) == 0)
            return true;
    return false;
}

#define FAIL(...)                                                                                                     \
    do {                                                                                                              \
        *err = xprintf(__VA_ARGS__);                                                                                  \
        goto fail;                                                                                                    \
    } while (0)

/* One statement; `place` is the open place block or nullptr. */
static bool statement(Script *s, Place **place, char **w, int nw, const char *where, char **err)
{
    const char *kw = w[0];
    long n;
    if (*place) {
        Place *p = *place;
        if (strcmp(kw, "end") == 0) {
            if (nw != 1)
                FAIL("%s: 'end' takes nothing", where);
            vec_push(s->places, *p);
            free(p);
            *place = nullptr;
        } else if (section_type(kw) >= 0) {
            if (nw > 2)
                FAIL("%s: expected  %s [NAME | *]", where, kw);
            char *name = nullptr;
            if (nw == 2) {
                if (strcmp(w[1], "*") != 0 && !check_name(w[1], where, "section", err))
                    goto fail;
                name = xstrdup(w[1]);
            }
            vec_push(p->items, ((PlaceItem){PI_SECTION, xstrdup(where), (SecType)section_type(kw), name, 0}));
        } else if (strcmp(kw, "align") == 0) {
            if (nw != 2)
                FAIL("%s: expected  align N", where);
            if (!parse_number(w[1], &n))
                FAIL("%s: bad number '%s'", where, w[1]);
            if (n < 1)
                FAIL("%s: align needs a positive number", where);
            vec_push(p->items, ((PlaceItem){PI_ALIGN, xstrdup(where), SEC_CODE, nullptr, n}));
        } else if (strcmp(kw, "symbol") == 0) {
            if (nw != 2)
                FAIL("%s: inside 'place' a symbol takes the current address: symbol NAME", where);
            if (!check_name(w[1], where, "symbol", err))
                goto fail;
            vec_push(p->items, ((PlaceItem){PI_SYMBOL, xstrdup(where), SEC_CODE, xstrdup(w[1]), 0}));
        } else {
            FAIL("%s: '%s' is not allowed inside 'place' (code, data, bss, align, symbol, end)", where, kw);
        }
        return true;
    }

    if (strcmp(kw, "memory") == 0) {
        if (nw != 6 || strcmp(w[2], "start") != 0 || strcmp(w[4], "size") != 0)
            FAIL("%s: expected  memory NAME start ADDR size BYTES", where);
        if (!check_name(w[1], where, "region", err))
            goto fail;
        if (script_region(s, w[1]))
            FAIL("%s: region '%s' already declared", where, w[1]);
        Region r = {.name = xstrdup(w[1]), .where = xstrdup(where)};
        if (!parse_number(w[3], &r.start))
            FAIL("%s: bad number '%s'", where, w[3]);
        if (!parse_number(w[5], &r.size))
            FAIL("%s: bad number '%s'", where, w[5]);
        if (r.size < 1 || r.start + r.size > 0x10000)
            FAIL("%s: region '%s' must lie within 0x0000 .. 0xFFFF", where, r.name);
        for (size_t i = 0; i < s->regions.n; i++) {
            const Region *o = &s->regions.v[i];
            if (r.start < o->start + o->size && o->start < r.start + r.size)
                FAIL("%s: region '%s' overlaps '%s'", where, r.name, o->name);
        }
        vec_push(s->regions, r);
    } else if (strcmp(kw, "place") == 0) {
        if (nw != 2)
            FAIL("%s: expected  place REGION", where);
        if (!script_region(s, w[1]))
            FAIL("%s: unknown region '%s'", where, w[1]);
        if (has_place(s, w[1]))
            FAIL("%s: region '%s' already has a place block", where, w[1]);
        *place = xcalloc(1, sizeof **place);
        (*place)->region = xstrdup(w[1]);
        (*place)->where = xstrdup(where);
    } else if (strcmp(kw, "symbol") == 0) {
        ScriptSym sym = {.where = xstrdup(where)};
        if (nw == 4 && strcmp(w[2], "=") == 0) {
            if (!check_name(w[1], where, "symbol", err))
                goto fail;
            sym.name = xstrdup(w[1]);
            sym.kind = SS_NUMBER;
            if (!parse_number(w[3], &sym.value))
                FAIL("%s: bad number '%s'", where, w[3]);
            if (sym.value < 0 || sym.value > 0xFFFF)
                FAIL("%s: value out of range", where);
        } else if (nw == 5 && strcmp(w[2], "=") == 0 && (strcmp(w[3], "start") == 0 || strcmp(w[3], "last") == 0)) {
            if (!script_region(s, w[4]))
                FAIL("%s: unknown region '%s'", where, w[4]);
            if (!check_name(w[1], where, "symbol", err))
                goto fail;
            sym.name = xstrdup(w[1]);
            sym.kind = w[3][0] == 's' ? SS_START : SS_LAST;
            sym.region = xstrdup(w[4]);
        } else {
            FAIL("%s: expected  symbol NAME = NUMBER | start REGION | last REGION", where);
        }
        vec_push(s->symbols, sym);
    } else if (section_type(kw) >= 0 || strcmp(kw, "align") == 0 || strcmp(kw, "end") == 0) {
        FAIL("%s: '%s' is only allowed inside a 'place' block", where, kw);
    } else {
        FAIL("%s: unknown statement '%s' (memory, place, symbol)", where, kw);
    }
    return true;
fail:
    return false;
}

bool script_parse(const char *text, const char *path, Script *s, char **err)
{
    *s = (Script){.path = xstrdup(path)};
    Place *place = nullptr;
    long line_no = 0;
    bool ok = true;
    for (const char *p = text; ok;) {
        line_no++;
        const char *nl = strchr(p, '\n');
        size_t len = nl ? (size_t)(nl - p) : strlen(p);
        const char *semi = memchr(p, ';', len);
        if (semi)
            len = (size_t)(semi - p);
        StrList words = {};
        for (size_t i = 0; i < len;) {
            while (i < len && py_space((unsigned char)p[i]))
                i++;
            size_t st = i;
            while (i < len && !py_space((unsigned char)p[i]))
                i++;
            if (i > st)
                vec_push(words, xstrndup(p + st, i - st));
        }
        if (words.n) {
            char *where = xprintf("%s:%ld", path, line_no);
            ok = statement(s, &place, words.v, (int)words.n, where, err);
            free(where);
        }
        strlist_free(&words);
        if (!nl)
            break;
        p = nl + 1;
    }
    if (ok && place) {
        *err = xprintf("%s: 'place' block is not closed with 'end'", place->where);
        ok = false;
    }
    return ok;
}

bool script_load(const char *path, Script *s, char **err)
{
    char *text = read_file(path, nullptr);
    if (!text) {
        *err = xprintf("cannot read '%s': %s", path, strerror(errno));
        return false;
    }
    bool ok = script_parse(text, path, s, err);
    free(text);
    return ok;
}
