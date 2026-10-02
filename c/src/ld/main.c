/* sra8-ld -- link objects into an image, driven by a linker script.
 *
 *   sra8-ld [-T script.ld] [-o out] [--format bin|mem|ihex] [--mem-size N]
 *           [-M out.map] objects...
 */
#include <stdlib.h>
#include <string.h>

#include "ld.h"

#ifndef SRA8_DEFAULT_SCRIPT
#define SRA8_DEFAULT_SCRIPT "ldscripts/boot.ld"
#endif

static void usage(FILE *f)
{
    fputs("usage: sra8-ld [-h] [-T SCRIPT] [-o OUTPUT] [--format {bin,mem,ihex}]\n"
          "               [--mem-size MEM_SIZE] [-M MAP]\n"
          "               objects [objects ...]\n",
          f);
}

static void help(void)
{
    usage(stdout);
    fputs("\nSRA-8 linker: objects + script -> image\n\n"
          "positional arguments:\n"
          "  objects               object files, linked in this order\n\n"
          "options:\n"
          "  -h, --help            show this help message and exit\n"
          "  -T, --script SCRIPT   linker script (default: " SRA8_DEFAULT_SCRIPT ")\n"
          "  -o, --output OUTPUT   output file (default: a.bin, a.mem or a.hex)\n"
          "  --format {bin,mem,ihex}\n"
          "  --mem-size MEM_SIZE   bytes in a .mem image (default 4096, the boot ROM)\n"
          "  -M, --map MAP         write a map file\n",
          stdout);
}

[[noreturn]] static void bad_args(const char *msg)
{
    usage(stderr);
    fprintf(stderr, "sra8-ld: error: %s\n", msg);
    exit(2);
}

static const char *value(int argc, char **argv, int *i, const char *name)
{
    const char *a = argv[*i];
    size_t n = strlen(name);
    if (strncmp(a, name, n) == 0 && a[n] == '=')
        return a + n + 1;
    if (++*i >= argc) {
        char *m = xprintf("argument %s: expected one argument", name);
        bad_args(m);
    }
    return argv[*i];
}

static bool is_opt(const char *a, const char *s, const char *l)
{
    size_t n = l ? strlen(l) : 0;
    return (s && strcmp(a, s) == 0) || (l && strncmp(a, l, n) == 0 && (a[n] == '\0' || a[n] == '='));
}

int main(int argc, char **argv)
{
    const char *script_path = SRA8_DEFAULT_SCRIPT, *output = nullptr, *format = "bin";
    const char *map = nullptr;
    long long mem_size = 4096;
    VEC(char *) objects = {};
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (strcmp(a, "-h") == 0 || strcmp(a, "--help") == 0) {
            help();
            return 0;
        } else if (is_opt(a, "-T", "--script")) {
            script_path = value(argc, argv, &i, a[1] == 'T' ? "-T" : "--script");
        } else if (is_opt(a, "-o", "--output")) {
            output = value(argc, argv, &i, a[1] == 'o' ? "-o" : "--output");
        } else if (is_opt(a, nullptr, "--format")) {
            format = value(argc, argv, &i, "--format");
            if (strcmp(format, "bin") && strcmp(format, "mem") && strcmp(format, "ihex")) {
                char *m = xprintf("argument --format: invalid choice: '%s' (choose from bin, mem, ihex)", format);
                bad_args(m);
            }
        } else if (is_opt(a, nullptr, "--mem-size")) {
            const char *v = value(argc, argv, &i, "--mem-size");
            if (!parse_int_auto(v, &mem_size) || mem_size < 0) {
                char *m = xprintf("argument --mem-size: invalid value: '%s'", v);
                bad_args(m);
            }
        } else if (is_opt(a, "-M", "--map")) {
            map = value(argc, argv, &i, a[1] == 'M' ? "-M" : "--map");
        } else if (a[0] == '-' && a[1]) {
            char *m = xprintf("unrecognized arguments: %s", a);
            bad_args(m);
        } else {
            vec_push(objects, (char *)a);
        }
    }
    if (!objects.n)
        bad_args("the following arguments are required: objects");

    char *err = nullptr;
    Script script;
    if (!script_load(script_path, &script, &err)) {
        fprintf(stderr, "error: %s\n", err);
        return 1;
    }
    Object *objs = xcalloc(objects.n, sizeof *objs);
    for (size_t i = 0; i < objects.n; i++) {
        if (!obj_read(objects.v[i], &objs[i], &err)) {
            fprintf(stderr, "error: %s\n", err);
            return 1;
        }
    }
    LinkResult res;
    StrList errors = {};
    if (!link_objects(&script, objects.v, objs, objects.n, &res, &errors)) {
        for (size_t i = 0; i < errors.n; i++)
            fprintf(stderr, "error: %s\n", errors.v[i]);
        return 1;
    }
    char *text = nullptr;
    if (strcmp(format, "mem") == 0) {
        text = mem_text(&res, (long)mem_size, &err);
        if (!text) {
            fprintf(stderr, "error: %s\n", err);
            return 1;
        }
    } else if (strcmp(format, "ihex") == 0) {
        text = ihex_text(&res);
    }
    const char *ext = strcmp(format, "mem") == 0 ? ".mem" : strcmp(format, "ihex") == 0 ? ".hex" : ".bin";
    char *out = output ? xstrdup(output) : xprintf("a%s", ext);
    bool ok = text ? write_file(out, text, strlen(text)) : write_file(out, res.image, (size_t)res.image_len);
    if (!ok) {
        fprintf(stderr, "error: cannot write '%s'\n", out);
        return 1;
    }
    if (map) {
        char *m = map_text(&res, script_path);
        if (!write_file(map, m, strlen(m))) {
            fprintf(stderr, "error: cannot write '%s'\n", map);
            return 1;
        }
        free(m);
    }
    free(text);
    free(out);
    return 0;
}
