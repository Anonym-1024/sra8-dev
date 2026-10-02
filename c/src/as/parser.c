/* parser.c -- lexical rules and operand parsing (spec 3.1-3.4). */
#include <stdlib.h>
#include <string.h>

#include "asm.h"

AsmErr *unescape(const char *s, size_t n, Str *out)
{
    for (size_t i = 0; i < n; i++) {
        if (s[i] != '\\') {
            str_addc(out, s[i]);
            continue;
        }
        char c = ++i < n ? s[i] : '\0';
        switch (c) {
        case 'n': str_addc(out, '\n'); break;
        case 't': str_addc(out, '\t'); break;
        case 'r': str_addc(out, '\r'); break;
        case '0': str_addc(out, '\0'); break;
        case '\\': str_addc(out, '\\'); break;
        case '\'': str_addc(out, '\''); break;
        case '"': str_addc(out, '"'); break;
        default:
            return asm_err("bad escape sequence in '%.*s'", (int)n, s);
        }
    }
    return nullptr;
}

static bool is_hex(int c)
{
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}

static bool all_hex(const char *s)
{
    if (!*s)
        return false;
    for (; *s; s++)
        if (!is_hex((unsigned char)*s))
            return false;
    return true;
}

static bool is_prefix(const char *s)
{
    return s[0] == '0' && s[1] && strchr("bBoOdDxX", s[1]);
}

/* [+-]?(0[bBoOdDxX])?[0-9A-Fa-f]+ */
static bool number_shape(const char *t)
{
    if (*t == '+' || *t == '-')
        t++;
    return (is_prefix(t) && all_hex(t + 2)) || all_hex(t);
}

AsmErr *parse_number(const char *text_in, long long *out)
{
    char *text = strip_copy(text_in, strlen(text_in));
    AsmErr *e = nullptr;
    size_t n = strlen(text);
    if (n >= 3 && text[0] == '\'' && text[n - 1] == '\'') {
        Str ch = {};
        e = unescape(text + 1, n - 2, &ch);
        if (!e && ch.len != 1)
            e = asm_err("bad character constant %s", text);
        if (!e)
            *out = (unsigned char)ch.s[0];
        free(ch.s);
        free(text);
        return e;
    }
    if (!number_shape(text)) {
        if (n > 1 && strpbrk(text + 1, "+-*/()&|<>"))
            e = asm_err("expressions are not supported: '%s'", text);
        else
            e = asm_err("bad number '%s'", text);
        free(text);
        return e;
    }
    const char *body = text;
    int sign = 1;
    if (*body == '+' || *body == '-') {
        sign = *body == '-' ? -1 : 1;
        body++;
    }
    int base = 10;
    if (is_prefix(body)) {
        char p = (char)(body[1] | 0x20);
        base = p == 'b' ? 2 : p == 'o' ? 8 : p == 'd' ? 10 : 16;
        body += 2;
    }
    long long v = 0;
    bool ok = *body != '\0';
    for (const char *p = body; *p && ok; p++) {
        int d = *p <= '9' ? *p - '0' : (*p | 0x20) - 'a' + 10;
        if (d >= base || v > (0x7FFFFFFFFFFFFFFFLL - d) / base)
            ok = false;
        else
            v = v * base + d;
    }
    if (!ok)
        e = asm_err("bad number '%s'", text);
    else
        *out = sign * v;
    free(text);
    return e;
}

/* [rR]([0-9]|1[0-5])([aA]?) */
static bool parse_register(const char *t, int *n, bool *pair)
{
    if (t[0] != 'r' && t[0] != 'R')
        return false;
    const char *p = t + 1;
    if (p[0] == '1' && p[1] >= '0' && p[1] <= '5') {
        *n = 10 + (p[1] - '0');
        p += 2;
    } else if (p[0] >= '0' && p[0] <= '9') {
        *n = p[0] - '0';
        p += 1;
    } else {
        return false;
    }
    *pair = false;
    if (*p == 'a' || *p == 'A') {
        *pair = true;
        p++;
    }
    if (*p == '\0')
        return true;
    /* "r1" + "0".."5": the two-digit alternative may also fit */
    return false;
}

static const char *skip_space(const char *p)
{
    while (*p && py_space((unsigned char)*p))
        p++;
    return p;
}

/* (?:\.([bf])\s+)?=\s*(IDENT)\s*(?:([+-])\s*(.+))? */
AsmErr *parse_label_ref(const char *text, Operand *op)
{
    const char *p = text;
    char dir = 0;
    if (p[0] == '.' && (p[1] == 'b' || p[1] == 'f') && py_space((unsigned char)p[2])) {
        dir = p[1];
        p = skip_space(p + 2);
    }
    bool ok = *p == '=';
    size_t n = 0;
    const char *name = nullptr;
    long long offset = 0;
    char sign = 0;
    const char *num = nullptr;
    if (ok) {
        p = skip_space(p + 1);
        name = p;
        n = match_ident(p);
        ok = n > 0;
        p = skip_space(p + n);
        if (ok && *p) {
            if (*p == '+' || *p == '-') {
                sign = *p;
                num = skip_space(p + 1);
                ok = *num != '\0';
            } else {
                ok = false;
            }
        }
    }
    if (!ok) {
        if (text[0] == '=')
            return asm_err("bad label reference '%s' (only =label, =label + n, =label - n)", text);
        return asm_err("bad operand '%s'", text);
    }
    if (sign) {
        AsmErr *e = parse_number(num, &offset);
        if (e)
            return e;
        if (sign == '-')
            offset = -offset;
        if (offset < -0x8000 || offset > 0xFFFF)
            return asm_err("offset %lld out of range", offset);
    }
    *op = (Operand){.kind = OP_LABEL, .name = xstrndup(name, n), .dir = dir, .offset = offset};
    return nullptr;
}

AsmErr *parse_operand(const char *text, Operand *op)
{
    int n;
    bool pair;
    if (parse_register(text, &n, &pair)) {
        *op = (Operand){.kind = OP_REG, .n = n, .pair = pair};
        return nullptr;
    }
    if (text[0] == '#') {
        *op = (Operand){.kind = OP_IMM};
        return parse_number(text + 1, &op->value);
    }
    return parse_label_ref(text, op);
}

AsmErr *parse_value(const char *text, Operand *op)
{
    if (text[0] == '=' || text[0] == '.')
        return parse_label_ref(text, op);
    *op = (Operand){.kind = OP_IMM};
    return parse_number(text[0] == '#' ? text + 1 : text, &op->value);
}

AsmErr *split_operands(const char *text, StrList *out)
{
    Str cur = {};
    char quote = 0;
    bool escaped = false;
    for (const char *p = text; *p; p++) {
        char ch = *p;
        if (escaped) {
            str_addc(&cur, ch);
            escaped = false;
        } else if (quote) {
            str_addc(&cur, ch);
            if (ch == '\\')
                escaped = true;
            else if (ch == quote)
                quote = 0;
        } else if (ch == '"' || ch == '\'') {
            quote = ch;
            str_addc(&cur, ch);
        } else if (ch == ',') {
            vec_push(*out, strip_copy(str_cstr(&cur), cur.len));
            cur.len = 0;
            cur.s[0] = '\0';
        } else {
            str_addc(&cur, ch);
        }
    }
    if (quote) {
        free(cur.s);
        return asm_err("unterminated string");
    }
    char *rest = strip_copy(str_cstr(&cur), cur.len);
    free(cur.s);
    if (rest[0] || out->n)
        vec_push(*out, rest);
    else
        free(rest);
    for (size_t i = 0; i < out->n; i++)
        if (!out->v[i][0])
            return asm_err("empty operand");
    return nullptr;
}
