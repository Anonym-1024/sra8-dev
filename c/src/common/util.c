/* util.c -- memory, strings, files and small helpers shared by the tools. */
#include "util.h"

#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>

/* ---- memory ------------------------------------------------------------ */

void die(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    fputs("fatal: ", stderr);
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
    va_end(ap);
    exit(2);
}

void *xmalloc(size_t n)
{
    void *p = malloc(n ? n : 1);
    if (!p)
        die("out of memory");
    return p;
}

void *xcalloc(size_t n, size_t size)
{
    void *p = calloc(n ? n : 1, size ? size : 1);
    if (!p)
        die("out of memory");
    return p;
}

void *xrealloc(void *p, size_t n)
{
    p = realloc(p, n ? n : 1);
    if (!p)
        die("out of memory");
    return p;
}

char *xstrndup(const char *s, size_t n)
{
    char *p = xmalloc(n + 1);
    memcpy(p, s, n);
    p[n] = '\0';
    return p;
}

char *xstrdup(const char *s)
{
    return xstrndup(s, strlen(s));
}

char *xvprintf(const char *fmt, va_list ap)
{
    va_list ap2;
    va_copy(ap2, ap);
    int n = vsnprintf(nullptr, 0, fmt, ap2);
    va_end(ap2);
    if (n < 0)
        die("formatting failed");
    char *p = xmalloc((size_t)n + 1);
    vsnprintf(p, (size_t)n + 1, fmt, ap);
    return p;
}

char *xprintf(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    char *p = xvprintf(fmt, ap);
    va_end(ap);
    return p;
}

bool strlist_has(const StrList *l, const char *s)
{
    for (size_t i = 0; i < l->n; i++)
        if (strcmp(l->v[i], s) == 0)
            return true;
    return false;
}

void strlist_free(StrList *l)
{
    for (size_t i = 0; i < l->n; i++)
        free(l->v[i]);
    free(l->v);
    *l = (StrList){};
}

/* ---- string builder ------------------------------------------------------ */

void str_addn(Str *b, const char *s, size_t n)
{
    if (b->len + n + 1 > b->cap) {
        size_t cap = b->cap ? b->cap : 64;
        while (cap < b->len + n + 1)
            cap *= 2;
        b->s = xrealloc(b->s, cap);
        b->cap = cap;
    }
    memcpy(b->s + b->len, s, n);
    b->len += n;
    b->s[b->len] = '\0';
}

void str_add(Str *b, const char *s)
{
    str_addn(b, s, strlen(s));
}

void str_addc(Str *b, char c)
{
    str_addn(b, &c, 1);
}

void str_addf(Str *b, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    char *p = xvprintf(fmt, ap);
    va_end(ap);
    str_add(b, p);
    free(p);
}

/* Python pads by characters; count UTF-8 continuation bytes as nothing. */
void str_pad(Str *b, const char *s, int width)
{
    int chars = 0;
    for (const unsigned char *p = (const unsigned char *)s; *p; p++)
        if ((*p & 0xC0) != 0x80)
            chars++;
    str_add(b, s);
    for (; chars < width; chars++)
        str_addc(b, ' ');
}

char *str_take(Str *b)
{
    char *s = b->s ? b->s : xstrdup("");
    *b = (Str){};
    return s;
}

const char *str_cstr(Str *b)
{
    if (!b->s)
        str_addn(b, "", 0);
    return b->s;
}

/* ---- text ---------------------------------------------------------------- */

bool py_space(int c)
{
    c &= 0xFF;
    return c == ' ' || (c >= '\t' && c <= '\r') || (c >= 0x1C && c <= 0x1F) || c == 0x85 || c == 0xA0;
}

char *strip_copy(const char *s, size_t n)
{
    size_t a = 0;
    while (a < n && py_space((unsigned char)s[a]))
        a++;
    while (n > a && py_space((unsigned char)s[n - 1]))
        n--;
    return xstrndup(s + a, n - a);
}

bool is_ident_start(int c)
{
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '_';
}

bool is_ident_char(int c)
{
    return is_ident_start(c) || (c >= '0' && c <= '9') || c == '.';
}

size_t match_ident(const char *s)
{
    if (!is_ident_start((unsigned char)s[0]))
        return 0;
    size_t n = 1;
    while (is_ident_char((unsigned char)s[n]))
        n++;
    return n;
}

bool is_ident(const char *s)
{
    size_t n = match_ident(s);
    return n && s[n] == '\0';
}

char *latin1_to_utf8(const char *s, size_t n)
{
    Str b = {};
    for (size_t i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c < 0x80) {
            str_addc(&b, (char)c);
        } else {
            str_addc(&b, (char)(0xC0 | c >> 6));
            str_addc(&b, (char)(0x80 | (c & 0x3F)));
        }
    }
    return str_take(&b);
}

bool ends_with(const char *s, const char *suffix)
{
    size_t a = strlen(s), b = strlen(suffix);
    return a >= b && strcmp(s + a - b, suffix) == 0;
}

static int digit_value(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'z')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'Z')
        return c - 'A' + 10;
    return 99;
}

bool parse_int_auto(const char *s, long long *out)
{
    char *t = strip_copy(s, strlen(s));
    const char *p = t;
    int sign = 1;
    if (*p == '+' || *p == '-') {
        sign = *p == '-' ? -1 : 1;
        p++;
    }
    int base = 10;
    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X'))
        base = 16, p += 2;
    else if (p[0] == '0' && (p[1] == 'o' || p[1] == 'O'))
        base = 8, p += 2;
    else if (p[0] == '0' && (p[1] == 'b' || p[1] == 'B'))
        base = 2, p += 2;
    bool ok = *p != '\0';
    long long v = 0;
    for (; *p && ok; p++) {
        if (*p == '_' && p[1] && p[1] != '_')
            continue;
        int d = digit_value((unsigned char)*p);
        if (d >= base || v > (LLONG_MAX - d) / base)
            ok = false;
        else
            v = v * base + d;
    }
    free(t);
    *out = sign * v;
    return ok;
}

/* ---- files and paths ----------------------------------------------------- */

char *read_file(const char *path, size_t *len)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return nullptr;
    Str b = {};
    char buf[65536];
    size_t n;
    while ((n = fread(buf, 1, sizeof buf, f)) > 0)
        str_addn(&b, buf, n);
    int err = ferror(f) ? errno : 0;
    fclose(f);
    if (err) {
        free(b.s);
        errno = err;
        return nullptr;
    }
    if (len)
        *len = b.len;
    return str_take(&b);
}

bool write_file(const char *path, const void *data, size_t len)
{
    FILE *f = fopen(path, "wb");
    if (!f)
        return false;
    bool ok = fwrite(data, 1, len, f) == len;
    return fclose(f) == 0 && ok;
}

char *path_dirname(const char *p)
{
    const char *slash = strrchr(p, '/');
    if (!slash)
        return xstrdup("");
    size_t n = (size_t)(slash - p);
    while (n > 1 && p[n - 1] == '/')
        n--;
    return xstrndup(p, n ? n : 1);
}

char *path_join(const char *dir, const char *name)
{
    if (name[0] == '/' || dir[0] == '\0')
        return xstrdup(name);
    if (ends_with(dir, "/"))
        return xprintf("%s%s", dir, name);
    return xprintf("%s/%s", dir, name);
}

char *path_without_ext(const char *p)
{
    const char *base = strrchr(p, '/');
    base = base ? base + 1 : p;
    const char *b = base;
    while (*b == '.')
        b++;
    const char *dot = strrchr(b, '.');
    if (!dot)
        return xstrdup(p);
    return xstrndup(p, (size_t)(dot - p));
}

/* ---- sorting --------------------------------------------------------------- */

static void merge(char *a, char *tmp, size_t n, size_t size, int (*cmp)(const void *, const void *))
{
    if (n < 2)
        return;
    size_t h = n / 2;
    merge(a, tmp, h, size, cmp);
    merge(a + h * size, tmp, n - h, size, cmp);
    size_t i = 0, j = h, k = 0;
    while (i < h && j < n) {
        if (cmp(a + j * size, a + i * size) < 0)
            memcpy(tmp + k++ * size, a + j++ * size, size);
        else
            memcpy(tmp + k++ * size, a + i++ * size, size);
    }
    while (i < h)
        memcpy(tmp + k++ * size, a + i++ * size, size);
    while (j < n)
        memcpy(tmp + k++ * size, a + j++ * size, size);
    memcpy(a, tmp, n * size);
}

void stable_sort(void *base, size_t n, size_t size, int (*cmp)(const void *, const void *))
{
    if (n < 2)
        return;
    char *tmp = xmalloc(n * size);
    merge(base, tmp, n, size, cmp);
    free(tmp);
}
