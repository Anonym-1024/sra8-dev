/* util.h -- memory, strings, files and small helpers shared by the tools. */
#ifndef SRA8_UTIL_H
#define SRA8_UTIL_H

#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

/* ---- memory ------------------------------------------------------------ */

[[noreturn]] void die(const char *fmt, ...);
void *xmalloc(size_t n);
void *xcalloc(size_t n, size_t size);
void *xrealloc(void *p, size_t n);
char *xstrdup(const char *s);
char *xstrndup(const char *s, size_t n);
char *xprintf(const char *fmt, ...);
char *xvprintf(const char *fmt, va_list ap);

/* A growable array: VEC(int) v = {}; vec_push(v, 3); v.v[0], v.n */
#define VEC(T) struct { T *v; size_t n, cap; }
#define vec_push(V, X)                                                        \
    do {                                                                      \
        if ((V).n == (V).cap) {                                               \
            (V).cap = (V).cap ? 2 * (V).cap : 8;                              \
            (V).v = xrealloc((V).v, (V).cap * sizeof *(V).v);                 \
        }                                                                     \
        (V).v[(V).n++] = (X);                                                 \
    } while (0)

typedef VEC(char *) StrList;
bool strlist_has(const StrList *l, const char *s);
void strlist_free(StrList *l);

/* ---- string builder ------------------------------------------------------ */

typedef struct {
    char *s;
    size_t len, cap;
} Str;

void str_addn(Str *b, const char *s, size_t n);
void str_add(Str *b, const char *s);
void str_addc(Str *b, char c);
void str_addf(Str *b, const char *fmt, ...);
void str_pad(Str *b, const char *s, int width); /* like Python "%-Ns" */
char *str_take(Str *b);                         /* the buffer, NUL-terminated; b is reset */
const char *str_cstr(Str *b);                   /* NUL-terminated view */

/* ---- text ---------------------------------------------------------------- */

bool py_space(int c);                   /* Python's str.isspace() on Latin-1 */
char *strip_copy(const char *s, size_t n);
bool is_ident_start(int c);
bool is_ident_char(int c);              /* letters, digits, '_' and '.' */
size_t match_ident(const char *s);      /* length of [A-Za-z_][A-Za-z0-9_.]* at s, or 0 */
bool is_ident(const char *s);           /* the whole string is such a name */
char *latin1_to_utf8(const char *s, size_t n);
bool ends_with(const char *s, const char *suffix);
bool parse_int_auto(const char *s, long long *out); /* Python int(s, 0) */

/* ---- files and paths ----------------------------------------------------- */

char *read_file(const char *path, size_t *len);    /* nullptr on failure, errno set */
bool write_file(const char *path, const void *data, size_t len);
char *path_dirname(const char *p);
char *path_join(const char *dir, const char *name);
char *path_without_ext(const char *p);             /* Python os.path.splitext(p)[0] */

/* ---- sorting --------------------------------------------------------------- */

/* A stable merge sort with the interface of qsort. */
void stable_sort(void *base, size_t n, size_t size, int (*cmp)(const void *, const void *));

#endif
