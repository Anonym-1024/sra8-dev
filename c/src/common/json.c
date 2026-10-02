/* json.c -- the small JSON subset needed for object files. */
#include "json.h"

#include <stdlib.h>
#include <string.h>

typedef struct {
    const char *p;
    char *err;
    int depth;
} Parser;

static void fail(Parser *ps, const char *msg)
{
    if (!ps->err)
        ps->err = xstrdup(msg);
}

static void skip_ws(Parser *ps)
{
    while (*ps->p == ' ' || *ps->p == '\t' || *ps->p == '\n' || *ps->p == '\r')
        ps->p++;
}

static Json *new_json(JType t)
{
    Json *j = xcalloc(1, sizeof *j);
    j->type = t;
    return j;
}

static void add_utf8(Str *b, unsigned long cp)
{
    if (cp < 0x80) {
        str_addc(b, (char)cp);
    } else if (cp < 0x800) {
        str_addc(b, (char)(0xC0 | cp >> 6));
        str_addc(b, (char)(0x80 | (cp & 0x3F)));
    } else if (cp < 0x10000) {
        str_addc(b, (char)(0xE0 | cp >> 12));
        str_addc(b, (char)(0x80 | (cp >> 6 & 0x3F)));
        str_addc(b, (char)(0x80 | (cp & 0x3F)));
    } else {
        str_addc(b, (char)(0xF0 | cp >> 18));
        str_addc(b, (char)(0x80 | (cp >> 12 & 0x3F)));
        str_addc(b, (char)(0x80 | (cp >> 6 & 0x3F)));
        str_addc(b, (char)(0x80 | (cp & 0x3F)));
    }
}

static int hex4(const char *p)
{
    int v = 0;
    for (int i = 0; i < 4; i++) {
        char c = p[i];
        int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10
              : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
        if (d < 0)
            return -1;
        v = v * 16 + d;
    }
    return v;
}

static char *parse_string(Parser *ps)
{
    Str b = {};
    ps->p++; /* opening quote */
    for (;;) {
        unsigned char c = (unsigned char)*ps->p;
        if (c == '\0' || c < 0x20) {
            fail(ps, "unterminated or invalid string");
            free(b.s);
            return nullptr;
        }
        ps->p++;
        if (c == '"')
            break;
        if (c != '\\') {
            str_addc(&b, (char)c);
            continue;
        }
        char e = *ps->p++;
        switch (e) {
        case '"': str_addc(&b, '"'); break;
        case '\\': str_addc(&b, '\\'); break;
        case '/': str_addc(&b, '/'); break;
        case 'b': str_addc(&b, '\b'); break;
        case 'f': str_addc(&b, '\f'); break;
        case 'n': str_addc(&b, '\n'); break;
        case 'r': str_addc(&b, '\r'); break;
        case 't': str_addc(&b, '\t'); break;
        case 'u': {
            int cp = hex4(ps->p);
            if (cp < 0) {
                fail(ps, "bad \\u escape");
                free(b.s);
                return nullptr;
            }
            ps->p += 4;
            unsigned long code = (unsigned long)cp;
            if (cp >= 0xD800 && cp < 0xDC00 && ps->p[0] == '\\' && ps->p[1] == 'u') {
                int lo = hex4(ps->p + 2);
                if (lo >= 0xDC00 && lo < 0xE000) {
                    code = 0x10000 + (((unsigned long)cp - 0xD800) << 10) + ((unsigned long)lo - 0xDC00);
                    ps->p += 6;
                }
            }
            add_utf8(&b, code);
            break;
        }
        default:
            fail(ps, "bad escape");
            free(b.s);
            return nullptr;
        }
    }
    return str_take(&b);
}

static Json *parse_value(Parser *ps);

static Json *parse_array(Parser *ps)
{
    Json *j = new_json(J_ARR);
    VEC(Json *) items = {};
    ps->p++;
    skip_ws(ps);
    if (*ps->p == ']') {
        ps->p++;
        return j;
    }
    for (;;) {
        Json *v = parse_value(ps);
        if (!v)
            break;
        vec_push(items, v);
        skip_ws(ps);
        if (*ps->p == ',') {
            ps->p++;
            continue;
        }
        if (*ps->p == ']') {
            ps->p++;
            break;
        }
        fail(ps, "expected ',' or ']'");
        break;
    }
    j->items = items.v;
    j->n = items.n;
    return j;
}

static Json *parse_object(Parser *ps)
{
    Json *j = new_json(J_OBJ);
    VEC(Json *) items = {};
    StrList keys = {};
    ps->p++;
    skip_ws(ps);
    if (*ps->p == '}') {
        ps->p++;
        return j;
    }
    for (;;) {
        skip_ws(ps);
        if (*ps->p != '"') {
            fail(ps, "expected a key");
            break;
        }
        char *k = parse_string(ps);
        if (!k)
            break;
        skip_ws(ps);
        if (*ps->p != ':') {
            free(k);
            fail(ps, "expected ':'");
            break;
        }
        ps->p++;
        Json *v = parse_value(ps);
        if (!v) {
            free(k);
            break;
        }
        vec_push(keys, k);
        vec_push(items, v);
        skip_ws(ps);
        if (*ps->p == ',') {
            ps->p++;
            continue;
        }
        if (*ps->p == '}') {
            ps->p++;
            break;
        }
        fail(ps, "expected ',' or '}'");
        break;
    }
    j->items = items.v;
    j->keys = keys.v;
    j->n = items.n;
    return j;
}

static Json *parse_number(Parser *ps)
{
    const char *s = ps->p;
    bool is_float = false;
    if (*ps->p == '-')
        ps->p++;
    if (!(*ps->p >= '0' && *ps->p <= '9')) {
        fail(ps, "bad number");
        return nullptr;
    }
    while ((*ps->p >= '0' && *ps->p <= '9') || *ps->p == '.' || *ps->p == 'e' || *ps->p == 'E'
           || ((*ps->p == '+' || *ps->p == '-') && (ps->p[-1] == 'e' || ps->p[-1] == 'E'))) {
        if (*ps->p == '.' || *ps->p == 'e' || *ps->p == 'E')
            is_float = true;
        ps->p++;
    }
    Json *j = new_json(is_float ? J_FLOAT : J_INT);
    if (!is_float) {
        long long v = 0;
        bool neg = *s == '-';
        for (const char *q = s + neg; q < ps->p; q++) {
            if (v > (0x7FFFFFFFFFFFFFFFLL - 9) / 10) {
                j->type = J_FLOAT; /* too large: treated as not an integer */
                break;
            }
            v = v * 10 + (*q - '0');
        }
        j->i = neg ? -v : v;
    }
    return j;
}

static Json *parse_value(Parser *ps)
{
    if (++ps->depth > 64) {
        fail(ps, "nested too deep");
        return nullptr;
    }
    skip_ws(ps);
    Json *j = nullptr;
    char c = *ps->p;
    if (c == '{') {
        j = parse_object(ps);
    } else if (c == '[') {
        j = parse_array(ps);
    } else if (c == '"') {
        char *s = parse_string(ps);
        if (s) {
            j = new_json(J_STR);
            j->s = s;
        }
    } else if (strncmp(ps->p, "true", 4) == 0) {
        ps->p += 4;
        j = new_json(J_BOOL);
        j->b = true;
    } else if (strncmp(ps->p, "false", 5) == 0) {
        ps->p += 5;
        j = new_json(J_BOOL);
    } else if (strncmp(ps->p, "null", 4) == 0) {
        ps->p += 4;
        j = new_json(J_NULL);
    } else if (c == '-' || (c >= '0' && c <= '9')) {
        j = parse_number(ps);
    } else {
        fail(ps, "unexpected character");
    }
    ps->depth--;
    return j;
}

Json *json_parse(const char *text, char **err)
{
    Parser ps = {.p = text};
    Json *j = parse_value(&ps);
    skip_ws(&ps);
    if (!ps.err && *ps.p != '\0')
        fail(&ps, "extra data after the document");
    if (ps.err) {
        json_free(j);
        *err = ps.err;
        return nullptr;
    }
    return j;
}

void json_free(Json *j)
{
    if (!j)
        return;
    for (size_t i = 0; i < j->n; i++) {
        json_free(j->items[i]);
        if (j->keys)
            free(j->keys[i]);
    }
    free(j->items);
    free(j->keys);
    free(j->s);
    free(j);
}

const Json *json_get(const Json *obj, const char *key)
{
    if (!obj || obj->type != J_OBJ)
        return nullptr;
    const Json *found = nullptr;
    for (size_t i = 0; i < obj->n; i++)
        if (strcmp(obj->keys[i], key) == 0)
            found = obj->items[i]; /* the last one wins, as in Python */
    return found;
}

void json_write_str(Str *b, const char *s)
{
    str_addc(b, '"');
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        switch (*p) {
        case '"': str_add(b, "\\\""); break;
        case '\\': str_add(b, "\\\\"); break;
        case '\n': str_add(b, "\\n"); break;
        case '\r': str_add(b, "\\r"); break;
        case '\t': str_add(b, "\\t"); break;
        case '\b': str_add(b, "\\b"); break;
        case '\f': str_add(b, "\\f"); break;
        default:
            if (*p < 0x20)
                str_addf(b, "\\u%04x", *p);
            else
                str_addc(b, (char)*p);
        }
    }
    str_addc(b, '"');
}
