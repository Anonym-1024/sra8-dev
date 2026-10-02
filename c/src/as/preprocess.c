/* preprocess.c -- text preprocessor of the assembler: !INCLUDE, !DEFINE and
 * !alias (spec 3.7), plus the rule that ';' is the only comment syntax.
 * Source files are read as Latin-1 bytes. */
#include <errno.h>
#include <stdlib.h>
#include <string.h>

#include "asm.h"

enum { MAX_INCLUDE_DEPTH = 32, MAX_EXPAND_DEPTH = 32 };

/* ---- errors ---------------------------------------------------------------- */

AsmErr *asm_err(const char *fmt, ...)
{
    AsmErr *e = xcalloc(1, sizeof *e);
    va_list ap;
    va_start(ap, fmt);
    e->msg = xvprintf(fmt, ap);
    va_end(ap);
    return e;
}

void asm_err_locate(AsmErr *e, const char *where)
{
    if (!e->where)
        e->where = xstrdup(where);
}

char *asm_err_str(const AsmErr *e)
{
    return e->where ? xprintf("%s: %s", e->where, e->msg) : xstrdup(e->msg);
}

void asm_err_free(AsmErr *e)
{
    if (e) {
        free(e->msg);
        free(e->where);
        free(e);
    }
}

/* ---- comments and aliases --------------------------------------------------- */

typedef struct {
    char *name;
    char *text;
} Define;

typedef VEC(Define) Defines;

static const Define *find_define(const Defines *d, const char *name, size_t n)
{
    for (size_t i = 0; i < d->n; i++)
        if (strlen(d->v[i].name) == n && memcmp(d->v[i].name, name, n) == 0)
            return &d->v[i];
    return nullptr;
}

/* Cut a ';' comment, respecting quotes.  Reject C comments. */
static AsmErr *strip_comment(const char *text, size_t *len)
{
    char quote = 0;
    bool escaped = false;
    for (size_t i = 0; i < *len; i++) {
        char ch = text[i];
        if (escaped) {
            escaped = false;
        } else if (quote) {
            if (ch == '\\')
                escaped = true;
            else if (ch == quote)
                quote = 0;
        } else if (ch == '"' || ch == '\'') {
            quote = ch;
        } else if (ch == ';') {
            *len = i;
            return nullptr;
        } else if (ch == '/' && i + 1 < *len && (text[i + 1] == '/' || text[i + 1] == '*')) {
            return asm_err("'/%c' is not a comment here: only ';' starts a comment", text[i + 1]);
        }
    }
    return nullptr;
}

static size_t alias_len(const char *s)
{
    if (!is_ident_start((unsigned char)s[0]))
        return 0;
    size_t n = 1;
    while (is_ident_start((unsigned char)s[n]) || (s[n] >= '0' && s[n] <= '9'))
        n++;
    return n;
}

/* Replace every !alias outside quotes, repeatedly, so aliases may nest. */
static AsmErr *expand_aliases(const char *text, const Defines *defs, char **out)
{
    char *cur = xstrdup(text);
    for (int round = 0; round < MAX_EXPAND_DEPTH; round++) {
        Str b = {};
        char quote = 0;
        bool changed = false;
        for (size_t i = 0; cur[i];) {
            char ch = cur[i];
            size_t n = (ch == '!' && !quote) ? alias_len(cur + i + 1) : 0;
            if (n) {
                const Define *d = find_define(defs, cur + i + 1, n);
                if (!d) {
                    AsmErr *e = asm_err("undefined alias '!%.*s'", (int)n, cur + i + 1);
                    free(b.s);
                    free(cur);
                    return e;
                }
                str_add(&b, d->text);
                changed = true;
                i += n + 1;
                continue;
            }
            if (quote) {
                if (ch == '\\' && cur[i + 1]) {
                    str_addc(&b, ch);
                    i++;
                    ch = cur[i];
                } else if (ch == quote) {
                    quote = 0;
                }
            } else if (ch == '"' || ch == '\'') {
                quote = ch;
            }
            str_addc(&b, ch);
            i++;
        }
        free(cur);
        cur = str_take(&b);
        if (!changed) {
            *out = cur;
            return nullptr;
        }
    }
    free(cur);
    return asm_err("alias expansion too deep (recursive !DEFINE?)");
}

/* ---- the preprocessor ------------------------------------------------------------- */

/* Python str.split(None, 2) on an already stripped line. */
static int split_words(const char *t, char *w[3])
{
    int n = 0;
    const char *p = t;
    while (*p && n < 3) {
        while (*p && py_space((unsigned char)*p))
            p++;
        if (!*p)
            break;
        if (n == 2) {
            w[n++] = xstrdup(p);
            break;
        }
        const char *s = p;
        while (*p && !py_space((unsigned char)*p))
            p++;
        w[n++] = xstrndup(s, (size_t)(p - s));
    }
    return n;
}

static bool all_upper(const char *s)
{
    bool cased = false;
    for (; *s; s++) {
        if (*s >= 'a' && *s <= 'z')
            return false;
        if (*s >= 'A' && *s <= 'Z')
            cased = true;
    }
    return cased;
}

static AsmErr *line(const char *path, long line_no, const char *raw, size_t len, Defines *defs, SrcLines *out,
                    int depth);

static AsmErr *pp_file(const char *path, Defines *defs, SrcLines *out, int depth)
{
    if (depth > MAX_INCLUDE_DEPTH) {
        AsmErr *e = asm_err("!INCLUDE nested too deep");
        e->where = xstrdup(path);
        return e;
    }
    size_t len;
    char *data = read_file(path, &len);
    if (!data)
        return asm_err("cannot read '%s': %s", path, strerror(errno));
    long line_no = 1;
    size_t start = 0;
    for (size_t i = 0; i <= len; i++) {
        if (i < len && data[i] != '\n')
            continue;
        size_t n = i - start;
        if (n && data[start + n - 1] == '\r')
            n--;
        AsmErr *e = line(path, line_no, data + start, n, defs, out, depth);
        if (e) {
            char *where = xprintf("%s:%ld", path, line_no);
            asm_err_locate(e, where);
            free(where);
            free(data);
            return e;
        }
        line_no++;
        start = i + 1;
    }
    free(data);
    return nullptr;
}

static AsmErr *line(const char *path, long line_no, const char *raw, size_t len, Defines *defs, SrcLines *out,
                    int depth)
{
    AsmErr *e = strip_comment(raw, &len);
    if (e)
        return e;
    char *text = strip_copy(raw, len);
    if (!text[0]) {
        free(text);
        return nullptr;
    }
    char *w[3] = {};
    int nw = split_words(text, w);
    if (strcmp(w[0], "!INCLUDE") == 0) {
        char *rest = strip_copy(text + strlen("!INCLUDE"), strlen(text) - strlen("!INCLUDE"));
        char *name = nullptr;
        e = expand_aliases(rest, defs, &name);
        free(rest);
        if (!e && !name[0])
            e = asm_err("expected  !INCLUDE file");
        if (!e) {
            char *dir = path_dirname(path);
            char *inc = path_join(dir, name);
            e = pp_file(inc, defs, out, depth + 1);
            free(dir);
            free(inc);
        }
        free(name);
    } else if (strcmp(w[0], "!DEFINE") == 0) {
        if (nw < 2 || w[1][0] == '\0' || alias_len(w[1]) != strlen(w[1])) {
            e = asm_err("expected  !DEFINE <alias> <replacement>");
        } else {
            const Define *d = find_define(defs, w[1], strlen(w[1]));
            char *t = xstrdup(nw == 3 ? w[2] : "");
            if (d) {
                free(((Define *)d)->text);
                ((Define *)d)->text = t;
            } else {
                vec_push(*defs, ((Define){xstrdup(w[1]), t}));
            }
        }
    } else if (w[0][0] == '!' && all_upper(w[0] + 1) && !find_define(defs, w[0] + 1, strlen(w[0] + 1))) {
        e = asm_err("unknown preprocessor directive or undefined alias '%s'", w[0]);
    } else {
        char *exp = nullptr;
        e = expand_aliases(text, defs, &exp);
        if (!e)
            vec_push(*out, ((SrcLine){xstrdup(path), line_no, exp}));
    }
    for (int i = 0; i < nw; i++)
        free(w[i]);
    free(text);
    return e;
}

AsmErr *preprocess(const char *path, SrcLines *out)
{
    Defines defs = {};
    AsmErr *e = pp_file(path, &defs, out, 0);
    for (size_t i = 0; i < defs.n; i++) {
        free(defs.v[i].name);
        free(defs.v[i].text);
    }
    free(defs.v);
    return e;
}
