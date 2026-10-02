/* obj.c -- object files: JSON reading and writing, relocation patching. */
#include "obj.h"

#include <errno.h>
#include <stdlib.h>
#include <string.h>

#include "json.h"

const char *const SEC_TYPE_NAMES[3] = {"code", "data", "bss"};
const char *const REL_TYPE_NAMES[2] = {"IMM16", "ABS16"};

static constexpr char FORMAT[] = "sra8-obj";
static constexpr int VERSION = 2;

char *section_label(const Section *s)
{
    if (s->name[0])
        return xprintf("%s:%s", SEC_TYPE_NAMES[s->type], s->name);
    return xstrdup(SEC_TYPE_NAMES[s->type]);
}

const Export *obj_export(const Object *o, const char *name)
{
    for (size_t i = 0; i < o->exports.n; i++)
        if (strcmp(o->exports.v[i].name, name) == 0)
            return &o->exports.v[i];
    return nullptr;
}

void obj_imports(const Object *o, StrList *out)
{
    for (size_t i = 0; i < o->relocs.n; i++) {
        const char *s = o->relocs.v[i].symbol;
        if (s && !strlist_has(out, s))
            vec_push(*out, xstrdup(s));
    }
}

void section_append(Section *s, const uint8_t *data, long n)
{
    if (s->size + n > s->cap) {
        long cap = s->cap ? s->cap : 64;
        while (cap < s->size + n)
            cap *= 2;
        s->data = xrealloc(s->data, (size_t)cap);
        s->cap = cap;
    }
    memcpy(s->data + s->size, data, (size_t)n);
    s->size += n;
}

/* ---- writing: one list element per line, Python json.dumps separators --- */

static void key(Str *b, const char *k)
{
    json_write_str(b, k);
    str_add(b, ": ");
}

static void label_str(Str *b, const Object *o, int sec)
{
    char *l = section_label(&o->sections.v[sec]);
    json_write_str(b, l);
    free(l);
}

char *obj_to_json(const Object *o)
{
    Str b = {};
    str_add(&b, "{\n");
    str_addf(&b, "  \"format\": \"%s\",\n  \"version\": %d,\n  ", FORMAT, VERSION);
    key(&b, "source");
    json_write_str(&b, o->source);
    str_add(&b, ",\n");

    str_add(&b, o->sections.n ? "  \"sections\": [\n" : "  \"sections\": [],\n");
    for (size_t i = 0; i < o->sections.n; i++) {
        const Section *s = &o->sections.v[i];
        str_add(&b, "    {\"section\": ");
        label_str(&b, o, (int)i);
        str_addf(&b, ", \"size\": %ld", s->size);
        if (s->type != SEC_BSS) {
            str_add(&b, ", \"data\": \"");
            for (long k = 0; k < s->size; k++)
                str_addf(&b, "%02X", s->data[k]);
            str_addc(&b, '"');
        }
        str_add(&b, i + 1 < o->sections.n ? "},\n" : "}\n");
    }
    if (o->sections.n)
        str_add(&b, "  ],\n");

    str_add(&b, o->exports.n ? "  \"exports\": [\n" : "  \"exports\": [],\n");
    for (size_t i = 0; i < o->exports.n; i++) {
        const Export *e = &o->exports.v[i];
        str_add(&b, "    {\"name\": ");
        json_write_str(&b, e->name);
        str_add(&b, ", \"section\": ");
        label_str(&b, o, e->section);
        str_addf(&b, ", \"offset\": %ld}%s\n", e->offset, i + 1 < o->exports.n ? "," : "");
    }
    if (o->exports.n)
        str_add(&b, "  ],\n");

    str_add(&b, o->relocs.n ? "  \"relocations\": [\n" : "  \"relocations\": []\n");
    for (size_t i = 0; i < o->relocs.n; i++) {
        const Reloc *r = &o->relocs.v[i];
        str_add(&b, "    {\"section\": ");
        label_str(&b, o, r->section);
        str_addf(&b, ", \"offset\": %ld, \"type\": \"%s\", ", r->offset, REL_TYPE_NAMES[r->type]);
        if (r->symbol) {
            str_add(&b, "\"import\": ");
            json_write_str(&b, r->symbol);
            str_addf(&b, ", \"addend\": %ld}", r->addend);
        } else {
            str_add(&b, "\"from\": ");
            label_str(&b, o, r->target);
            str_addf(&b, ", \"index\": %ld}", r->index);
        }
        str_add(&b, i + 1 < o->relocs.n ? ",\n" : "\n");
    }
    if (o->relocs.n)
        str_add(&b, "  ]\n");
    str_add(&b, "}\n");
    return str_take(&b);
}

bool obj_write(const char *path, const Object *o)
{
    char *text = obj_to_json(o);
    bool ok = write_file(path, text, strlen(text));
    free(text);
    return ok;
}

/* ---- reading ------------------------------------------------------------ */

static char *bad(const char *where, const char *what)
{
    return xprintf("%s: missing or invalid '%s'", where, what);
}

static bool get_int(const Json *d, const char *k, long *out)
{
    const Json *v = json_get(d, k);
    if (!v || v->type != J_INT)
        return false;
    *out = (long)v->i;
    return true;
}

static const char *get_str(const Json *d, const char *k)
{
    const Json *v = json_get(d, k);
    return v && v->type == J_STR ? v->s : nullptr;
}

static int hexval(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

/* "code", "code:vector" ... -> type and name; false if malformed */
static bool parse_label(const char *label, int *type, const char **name)
{
    for (int k = 0; k < 3; k++) {
        size_t n = strlen(SEC_TYPE_NAMES[k]);
        if (strncmp(label, SEC_TYPE_NAMES[k], n) != 0)
            continue;
        if (label[n] == '\0') {
            *type = k;
            *name = "";
            return true;
        }
        if (label[n] == ':' && is_ident(label + n + 1)) {
            *type = k;
            *name = label + n + 1;
            return true;
        }
    }
    return false;
}

static int find_section(const Object *o, const char *label)
{
    for (size_t i = 0; i < o->sections.n; i++) {
        char *l = section_label(&o->sections.v[i]);
        bool same = strcmp(l, label) == 0;
        free(l);
        if (same)
            return (int)i;
    }
    return -1;
}

static char *section_ref(const Json *d, const char *k, const char *where, const Object *o, int *sec)
{
    const char *label = get_str(d, k);
    if (!label)
        return bad(where, k);
    *sec = find_section(o, label);
    if (*sec < 0)
        return xprintf("%s: unknown section '%s'", where, label);
    return nullptr;
}

static char *read_sections(const Json *doc, const char *path, Object *o)
{
    const Json *secs = json_get(doc, "sections");
    for (size_t i = 0; secs && secs->type == J_ARR && i < secs->n; i++) {
        const Json *d = secs->items[i];
        char where[64 + 4096];
        snprintf(where, sizeof where, "%s: section %zu", path, i);
        const char *label = get_str(d, "section");
        if (!label)
            return bad(where, "section");
        int type;
        const char *name;
        if (!parse_label(label, &type, &name))
            return xprintf("%s: bad section '%s'", where, label);
        if (find_section(o, label) >= 0)
            return xprintf("%s: section '%s' listed twice", where, label);
        long size;
        if (!get_int(d, "size", &size))
            return bad(where, "size");
        Section s = {.type = (SecType)type, .name = xstrdup(name), .size = 0};
        if (type != SEC_BSS) {
            s.data = xmalloc(1);    /* present even when empty: not bss */
            const char *hex = get_str(d, "data");
            if (!hex)
                return bad(where, "data");
            size_t n = strlen(hex);
            if (n % 2)
                return xprintf("%s: bad data", where);
            for (size_t k = 0; k < n; k += 2) {
                int hi = hexval(hex[k]), lo = hexval(hex[k + 1]);
                if (hi < 0 || lo < 0)
                    return xprintf("%s: bad data", where);
                uint8_t byte = (uint8_t)(hi << 4 | lo);
                section_append(&s, &byte, 1);
            }
            if (s.size != size)
                return xprintf("%s: data is %ld bytes, size says %ld", where, s.size, size);
        }
        s.size = size;
        vec_push(o->sections, s);
    }
    return nullptr;
}

static char *read_rest(const Json *doc, const char *path, Object *o)
{
    const Json *exps = json_get(doc, "exports");
    for (size_t i = 0; exps && exps->type == J_ARR && i < exps->n; i++) {
        const Json *d = exps->items[i];
        char where[64 + 4096];
        snprintf(where, sizeof where, "%s: export %zu", path, i);
        const char *name = get_str(d, "name");
        if (!name)
            return bad(where, "name");
        Export e = {.name = xstrdup(name)};
        char *err = section_ref(d, "section", where, o, &e.section);
        if (err)
            return err;
        if (!get_int(d, "offset", &e.offset))
            return bad(where, "offset");
        vec_push(o->exports, e);
    }
    const Json *rels = json_get(doc, "relocations");
    for (size_t i = 0; rels && rels->type == J_ARR && i < rels->n; i++) {
        const Json *d = rels->items[i];
        char where[64 + 4096];
        snprintf(where, sizeof where, "%s: relocation %zu", path, i);
        Reloc r = {.target = -1};
        char *err = section_ref(d, "section", where, o, &r.section);
        if (err)
            return err;
        if (!get_int(d, "offset", &r.offset))
            return bad(where, "offset");
        const char *t = get_str(d, "type");
        if (!t)
            return bad(where, "type");
        if (strcmp(t, "IMM16") == 0)
            r.type = R_IMM16;
        else if (strcmp(t, "ABS16") == 0)
            r.type = R_ABS16;
        else
            return xprintf("%s: bad type '%s'", where, t);
        if (json_get(d, "import")) {
            const char *sym = get_str(d, "import");
            if (!sym)
                return bad(where, "import");
            r.symbol = xstrdup(sym);
            if (!get_int(d, "addend", &r.addend))
                return bad(where, "addend");
        } else {
            if ((err = section_ref(d, "from", where, o, &r.target)))
                return err;
            if (!get_int(d, "index", &r.index))
                return bad(where, "index");
        }
        long width = r.type == R_IMM16 ? 4 : 2;
        const Section *s = &o->sections.v[r.section];
        if (r.offset < 0 || r.offset + width > s->size || !s->data)
            return xprintf("%s: offset outside the section", where);
        vec_push(o->relocs, r);
    }
    return nullptr;
}

bool obj_from_json(const char *text, const char *path, Object *o, char **err)
{
    char *perr = nullptr;
    Json *doc = json_parse(text, &perr);
    if (!doc) {
        *err = xprintf("%s: not an object file (%s)", path, perr);
        free(perr);
        return false;
    }
    const char *fmt = get_str(doc, "format");
    if (doc->type != J_OBJ || !fmt || strcmp(fmt, FORMAT) != 0) {
        *err = xprintf("%s: not an sra8 object file", path);
        json_free(doc);
        return false;
    }
    long version;
    if (!get_int(doc, "version", &version) || version != VERSION) {
        const Json *v = json_get(doc, "version");
        char *found = v && v->type == J_INT ? xprintf("%lld", v->i) : xstrdup("None");
        *err = xprintf("%s: unsupported object version %s (expected %d)", path, found, VERSION);
        free(found);
        json_free(doc);
        return false;
    }
    *o = (Object){};
    const char *src = get_str(doc, "source");
    o->source = xstrdup(src ? src : path);
    char *e = read_sections(doc, path, o);
    if (!e)
        e = read_rest(doc, path, o);
    json_free(doc);
    if (e) {
        *err = e;
        return false;
    }
    return true;
}

bool obj_read(const char *path, Object *o, char **err)
{
    char *text = read_file(path, nullptr);
    if (!text) {
        *err = xprintf("cannot read '%s': %s", path, strerror(errno));
        return false;
    }
    bool ok = obj_from_json(text, path, o, err);
    free(text);
    return ok;
}

void obj_patch(uint8_t *data, long offset, RelType type, long value)
{
    value &= 0xFFFF;
    if (type == R_IMM16) {
        data[offset + 2] = (uint8_t)(value >> 8);
        data[offset + 3] = (uint8_t)(value & 0xFF);
    } else {
        data[offset] = (uint8_t)(value & 0xFF);
        data[offset + 1] = (uint8_t)(value >> 8);
    }
}
