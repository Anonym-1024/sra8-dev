/* sra8-as -- assemble one .s file into a relocatable object (.o).
 *
 *   sra8-as [-o out.o] [-l out.lst] [-Werror] file.s
 */
#include <stdlib.h>
#include <string.h>

#include "asm.h"

static void usage(FILE *f)
{
    fputs("usage: sra8-as [-h] [-o OUTPUT] [-l LISTING] [-Werror] source\n", f);
}

static void help(void)
{
    usage(stdout);
    fputs("\nSRA-8 assembler: .s -> .o\n\n"
          "options:\n"
          "  -h, --help            show this help message and exit\n"
          "  -o, --output OUTPUT   object file (default: source name with .o)\n"
          "  -l, --listing LISTING write a listing file\n"
          "  -Werror               treat warnings as errors\n",
          stdout);
}

[[noreturn]] static void bad_args(const char *msg)
{
    usage(stderr);
    fprintf(stderr, "sra8-as: error: %s\n", msg);
    exit(2);
}

/* "file:12: text" -> "file:12: KIND: text" */
static void print_tagged(const char *msg, const char *kind)
{
    const char *sep = strstr(msg, ": ");
    if (sep) {
        const char *colon = nullptr;
        for (const char *p = msg; p < sep; p++)
            if (*p == ':')
                colon = p;
        bool digits = colon && colon + 1 < sep;
        for (const char *p = colon ? colon + 1 : sep; digits && p < sep; p++)
            digits = *p >= '0' && *p <= '9';
        if (digits) {
            fprintf(stderr, "%.*s: %s: %s\n", (int)(sep - msg), msg, kind, sep + 2);
            return;
        }
    }
    fprintf(stderr, "%s: %s\n", kind, msg);
}

int main(int argc, char **argv)
{
    const char *source = nullptr, *output = nullptr, *listing = nullptr;
    bool werror = false;
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (strcmp(a, "-h") == 0 || strcmp(a, "--help") == 0) {
            help();
            return 0;
        } else if (strcmp(a, "-Werror") == 0) {
            werror = true;
        } else if (strcmp(a, "-o") == 0 || strcmp(a, "--output") == 0) {
            if (++i >= argc)
                bad_args("argument -o/--output: expected one argument");
            output = argv[i];
        } else if (strncmp(a, "--output=", 9) == 0) {
            output = a + 9;
        } else if (strcmp(a, "-l") == 0 || strcmp(a, "--listing") == 0) {
            if (++i >= argc)
                bad_args("argument -l/--listing: expected one argument");
            listing = argv[i];
        } else if (strncmp(a, "--listing=", 10) == 0) {
            listing = a + 10;
        } else if (a[0] == '-' && a[1]) {
            char *m = xprintf("unrecognized arguments: %s", a);
            bad_args(m);
        } else if (!source) {
            source = a;
        } else {
            char *m = xprintf("unrecognized arguments: %s", a);
            bad_args(m);
        }
    }
    if (!source)
        bad_args("the following arguments are required: source");

    SrcLines lines = {};
    AsmErr *e = preprocess(source, &lines);
    if (e) {
        if (e->where)
            fprintf(stderr, "%s: error: %s\n", e->where, e->msg);
        else
            fprintf(stderr, "error: %s\n", e->msg);
        return 1;
    }
    AsmResult res = {};
    assemble(&lines, source, &res);
    for (size_t i = 0; i < res.warnings.n; i++)
        print_tagged(res.warnings.v[i], "warning");
    for (size_t i = 0; i < res.errors.n; i++)
        print_tagged(res.errors.v[i], "error");
    if (res.errors.n || (res.warnings.n && werror))
        return 1;

    char *out = output ? xstrdup(output) : nullptr;
    if (!out) {
        char *base = path_without_ext(source);
        out = xprintf("%s.o", base);
        free(base);
    }
    if (!obj_write(out, &res.obj)) {
        fprintf(stderr, "error: cannot write '%s'\n", out);
        return 1;
    }
    if (listing) {
        char *text = asm_listing(&res);
        if (!write_file(listing, text, strlen(text))) {
            fprintf(stderr, "error: cannot write '%s'\n", listing);
            return 1;
        }
        free(text);
    }
    free(out);
    return 0;
}
