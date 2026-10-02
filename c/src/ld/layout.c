/* layout.c -- the link (spec 5.3): place sections, resolve symbols, relocate. */
#include <setjmp.h>
#include <stdlib.h>
#include <string.h>

#include "ld.h"

enum { MAX_ERRORS = 30 };

typedef struct {
    int obj, sec;
} Member;

typedef struct {
    SecType type;
    const char *name;
    VEC(Member) members;
    bool placed;
} Group;

typedef struct {
    char *name;
    long addr;
} Global;

typedef struct {
    char *name;
    int obj;
} Owner;

typedef struct {
    const Script *script;
    char **paths;
    Object *objects;
    size_t nobj;
    StrList *errors;
    jmp_buf too_many;
    long **base;
    VEC(Contribution) contribs;
    VEC(Global) globals;    /* script symbols, in definition order */
    VEC(Owner) owners;      /* exported name -> object */
    VEC(Group) groups;      /* in order of first appearance */
    VEC(RegionUse) regions;
} Linker;

static void err(Linker *l, char *msg)
{
    vec_push(*l->errors, msg);
    if (l->errors->n >= MAX_ERRORS) {
        vec_push(*l->errors, xstrdup("too many errors, stopping"));
        longjmp(l->too_many, 1);
    }
}

static const Owner *owner_of(const Linker *l, const char *name)
{
    for (size_t i = 0; i < l->owners.n; i++)
        if (strcmp(l->owners.v[i].name, name) == 0)
            return &l->owners.v[i];
    return nullptr;
}

static Global *global(Linker *l, const char *name)
{
    for (size_t i = 0; i < l->globals.n; i++)
        if (strcmp(l->globals.v[i].name, name) == 0)
            return &l->globals.v[i];
    return nullptr;
}

static void set_global(Linker *l, const char *name, long addr)
{
    Global *g = global(l, name);
    if (g)
        g->addr = addr;
    else
        vec_push(l->globals, ((Global){xstrdup(name), addr}));
}

static long align_up(long addr, long n)
{
    return (addr + n - 1) / n * n;
}

/* ---- step 1: exports ------------------------------------------------------- */

static void collect_exports(Linker *l)
{
    for (size_t i = 0; i < l->nobj; i++) {
        const Object *o = &l->objects[i];
        for (size_t k = 0; k < o->exports.n; k++) {
            const Export *s = &o->exports.v[k];
            const Owner *w = owner_of(l, s->name);
            if (w)
                err(l, xprintf("'%s' is exported by both %s and %s", s->name, l->paths[w->obj], l->paths[i]));
            else
                vec_push(l->owners, ((Owner){s->name, (int)i}));
        }
    }
    StrList names = {};
    for (size_t i = 0; i < l->script->symbols.n; i++) {
        const ScriptSym *s = &l->script->symbols.v[i];
        if (strlist_has(&names, s->name))
            err(l, xprintf("%s: script symbol '%s' defined twice", s->where, s->name));
        else
            vec_push(names, s->name);
    }
    for (size_t p = 0; p < l->script->places.n; p++) {
        const Place *pl = &l->script->places.v[p];
        for (size_t k = 0; k < pl->items.n; k++) {
            const PlaceItem *it = &pl->items.v[k];
            if (it->kind != PI_SYMBOL)
                continue;
            if (strlist_has(&names, it->name))
                err(l, xprintf("%s: script symbol '%s' defined twice", it->where, it->name));
            else
                vec_push(names, it->name);
        }
    }
    for (size_t i = 0; i < names.n; i++) {
        const Owner *w = owner_of(l, names.v[i]);
        if (w)
            err(l, xprintf("script symbol '%s' is also exported by %s", names.v[i], l->paths[w->obj]));
    }
    free(names.v);
}

/* ---- step 2: placement ----------------------------------------------------- */

static void make_groups(Linker *l)
{
    for (size_t i = 0; i < l->nobj; i++) {
        const Object *o = &l->objects[i];
        for (size_t j = 0; j < o->sections.n; j++) {
            const Section *s = &o->sections.v[j];
            Group *g = nullptr;
            for (size_t k = 0; k < l->groups.n && !g; k++)
                if (l->groups.v[k].type == s->type && strcmp(l->groups.v[k].name, s->name) == 0)
                    g = &l->groups.v[k];
            if (!g) {
                vec_push(l->groups, ((Group){.type = s->type, .name = s->name}));
                g = &l->groups.v[l->groups.n - 1];
            }
            vec_push(g->members, ((Member){(int)i, (int)j}));
        }
    }
}

static long place_group(Linker *l, Group *g, long cur, const Region *r, const char *where)
{
    long end = r->start + r->size;
    for (size_t k = 0; k < g->members.n; k++) {
        Member m = g->members.v[k];
        const Section *s = &l->objects[m.obj].sections.v[m.sec];
        if (s->type == SEC_CODE)
            cur = align_up(cur, ISA_INSTR_SIZE);
        if (cur + s->size > end) {
            char *label = section_label(s);
            err(l, xprintf("%s: section %s of %s (%ld bytes at 0x%04lX) does not fit into region '%s' (ends at 0x%04lX)",
                           where, label, l->paths[m.obj], s->size, cur, r->name, end - 1));
            free(label);
            return end;
        }
        l->base[m.obj][m.sec] = cur;
        uint8_t *data = nullptr;
        if (s->data) {
            data = xmalloc((size_t)s->size + 1);
            memcpy(data, s->data, (size_t)s->size);
        }
        vec_push(l->contribs, ((Contribution){m.obj, m.sec, s->type, s->name, cur, s->size, data}));
        cur += s->size;
    }
    return cur;
}

static void place(Linker *l)
{
    make_groups(l);
    for (size_t p = 0; p < l->script->places.n; p++) {
        const Place *pl = &l->script->places.v[p];
        const Region *r = script_region(l->script, pl->region);
        long end = r->start + r->size, cur = r->start;
        for (size_t k = 0; k < pl->items.n; k++) {
            const PlaceItem *it = &pl->items.v[k];
            if (it->kind == PI_ALIGN) {
                cur = align_up(cur, it->value);
            } else if (it->kind == PI_SYMBOL) {
                set_global(l, it->name, cur);
            } else if (it->name && strcmp(it->name, "*") == 0) {
                for (int named = 0; named < 2; named++)
                    for (size_t g = 0; g < l->groups.n; g++) {
                        Group *gr = &l->groups.v[g];
                        if (gr->type == it->stype && (gr->name[0] != '\0') == named && !gr->placed) {
                            gr->placed = true;
                            cur = place_group(l, gr, cur, r, it->where);
                        }
                    }
            } else {
                const char *name = it->name ? it->name : "";
                for (size_t g = 0; g < l->groups.n; g++) {
                    Group *gr = &l->groups.v[g];
                    if (gr->type == it->stype && strcmp(gr->name, name) == 0 && !gr->placed) {
                        gr->placed = true;
                        cur = place_group(l, gr, cur, r, it->where);
                    }
                }
            }
            if (cur > end)
                cur = end;
        }
        vec_push(l->regions, ((RegionUse){r->name, r->start, r->size, cur - r->start}));
    }
    for (size_t g = 0; g < l->groups.n; g++) {
        const Group *gr = &l->groups.v[g];
        if (gr->placed)
            continue;
        for (size_t k = 0; k < gr->members.n; k++) {
            Member m = gr->members.v[k];
            const Object *o = &l->objects[m.obj];
            const Section *s = &o->sections.v[m.sec];
            bool used = false;
            for (size_t q = 0; q < o->exports.n; q++)
                used |= o->exports.v[q].section == m.sec;
            for (size_t q = 0; q < o->relocs.n; q++)
                used |= o->relocs.v[q].target == m.sec;
            if (s->size || used) {
                char *label = section_label(s);
                err(l, xprintf("section %s of %s is not placed by the linker script %s", label, l->paths[m.obj],
                               l->script->path));
                free(label);
            }
        }
    }
}

static void script_symbols(Linker *l)
{
    for (size_t i = 0; i < l->script->symbols.n; i++) {
        const ScriptSym *s = &l->script->symbols.v[i];
        const Region *r = s->region ? script_region(l->script, s->region) : nullptr;
        long v = s->kind == SS_NUMBER ? s->value : s->kind == SS_START ? r->start : r->start + r->size - 1;
        set_global(l, s->name, v);
    }
}

/* ---- steps 3 and 4: resolve and relocate ------------------------------------ */

static long base_of(const Linker *l, int obj, int sec)
{
    long b = l->base[obj][sec];
    return b < 0 ? 0 : b;
}

/* The address of an exported label or a script symbol. */
static bool imported(Linker *l, const char *name, long *addr)
{
    const Owner *w = owner_of(l, name);
    if (w) {
        const Export *e = obj_export(&l->objects[w->obj], name);
        *addr = base_of(l, w->obj, e->section) + e->offset;
        return true;
    }
    const Global *g = global(l, name);
    if (g) {
        *addr = g->addr;
        return true;
    }
    return false;
}

static Contribution *contribution(Linker *l, int obj, int sec)
{
    for (size_t i = 0; i < l->contribs.n; i++)
        if (l->contribs.v[i].obj == obj && l->contribs.v[i].sec == sec)
            return &l->contribs.v[i];
    return nullptr;
}

static void relocate(Linker *l)
{
    typedef struct {
        const char *name;
        StrList users;
    } Unresolved;
    VEC(Unresolved) unresolved = {};
    for (size_t i = 0; i < l->nobj; i++) {
        const Object *o = &l->objects[i];
        for (size_t k = 0; k < o->relocs.n; k++) {
            const Reloc *r = &o->relocs.v[k];
            long value;
            if (r->symbol) {
                if (!imported(l, r->symbol, &value)) {
                    Unresolved *u = nullptr;
                    for (size_t q = 0; q < unresolved.n && !u; q++)
                        if (strcmp(unresolved.v[q].name, r->symbol) == 0)
                            u = &unresolved.v[q];
                    if (!u) {
                        vec_push(unresolved, ((Unresolved){r->symbol, {}}));
                        u = &unresolved.v[unresolved.n - 1];
                    }
                    if (!strlist_has(&u->users, l->paths[i]))
                        vec_push(u->users, l->paths[i]);
                    continue;
                }
                value += r->addend;
            } else {
                value = base_of(l, (int)i, r->target) + r->index;
            }
            Contribution *c = contribution(l, (int)i, r->section);
            if (c && c->data)
                obj_patch(c->data, r->offset, r->type, value);
        }
    }
    for (size_t q = 0; q < unresolved.n; q++) {
        Str users = {};
        for (size_t k = 0; k < unresolved.v[q].users.n; k++)
            str_addf(&users, k ? ", %s" : "%s", unresolved.v[q].users.v[k]);
        err(l, xprintf("undefined symbol '%s', imported by %s", unresolved.v[q].name, str_cstr(&users)));
        free(users.s);
    }
}

static void check(Linker *l)
{
    for (size_t i = 0; i < l->contribs.n; i++) {
        const Contribution *c = &l->contribs.v[i];
        if (c->stype == SEC_CODE && c->addr % ISA_INSTR_SIZE)
            err(l, xprintf("code section of %s at 0x%04lX is not 4-aligned", l->paths[c->obj], c->addr));
    }
}

/* ---- result ------------------------------------------------------------------ */

static int by_addr(const void *x, const void *y)
{
    const Contribution *a = x, *b = y;
    return a->addr < b->addr ? -1 : a->addr > b->addr;
}

static void result(Linker *l, LinkResult *res)
{
    *res = (LinkResult){.paths = l->paths, .objects = l->objects, .nobj = l->nobj, .base = l->base};
    res->regions.v = l->regions.v;
    res->regions.n = l->regions.n;
    res->contribs.v = l->contribs.v;
    res->contribs.n = l->contribs.n;
    stable_sort(res->contribs.v, res->contribs.n, sizeof *res->contribs.v, by_addr);
    for (size_t i = 0; i < l->nobj; i++) {
        const Object *o = &l->objects[i];
        for (size_t k = 0; k < o->exports.n; k++) {
            const Export *s = &o->exports.v[k];
            if (l->base[i][s->section] >= 0)
                vec_push(res->symbols, ((LinkedSymbol){s->name, l->base[i][s->section] + s->offset, LS_EXPORTED, (int)i}));
        }
    }
    for (size_t g = 0; g < l->globals.n; g++)
        if (!owner_of(l, l->globals.v[g].name))
            vec_push(res->symbols, ((LinkedSymbol){l->globals.v[g].name, l->globals.v[g].addr, LS_SCRIPT, -1}));

    long start = -1, end = 0;
    for (size_t i = 0; i < res->contribs.n; i++) {
        const Contribution *c = &res->contribs.v[i];
        if (!c->data || !c->size)
            continue;
        for (size_t r = 0; r < l->script->regions.n; r++) {
            const Region *rg = &l->script->regions.v[r];
            if (rg->start <= c->addr && c->addr < rg->start + rg->size && (start < 0 || rg->start < start))
                start = rg->start;
        }
        if (c->addr + c->size > end)
            end = c->addr + c->size;
    }
    if (start < 0) {
        res->image = xmalloc(1);
        return;
    }
    res->image_start = start;
    res->image_len = end - start;
    res->image = xcalloc((size_t)res->image_len + 1, 1);
    for (size_t i = 0; i < res->contribs.n; i++) {
        const Contribution *c = &res->contribs.v[i];
        if (c->data && c->size)
            memcpy(res->image + (c->addr - start), c->data, (size_t)c->size);
    }
}

bool link_objects(const Script *s, char **paths, Object *objects, size_t nobj, LinkResult *res, StrList *errors)
{
    Linker *l = xcalloc(1, sizeof *l);
    l->script = s;
    l->paths = paths;
    l->objects = objects;
    l->nobj = nobj;
    l->errors = errors;
    l->base = xcalloc(nobj + 1, sizeof *l->base);
    for (size_t i = 0; i < nobj; i++) {
        l->base[i] = xmalloc((objects[i].sections.n + 1) * sizeof **l->base);
        for (size_t j = 0; j <= objects[i].sections.n; j++)
            l->base[i][j] = -1;
    }
    if (setjmp(l->too_many))
        return false;
    collect_exports(l);
    place(l);
    script_symbols(l);
    if (!errors->n) {
        relocate(l);
        check(l);
    }
    if (errors->n)
        return false;
    result(l, res);
    return true;
}
