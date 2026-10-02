/* obj.h -- relocatable object files: a JSON text format (spec Section 4,
 * docs/obj.md).
 *
 * An object holds a header (format, version, source file name), the
 * sections, each identified by its label ("code", "code:vector",
 * "data:rodata", "bss" ...), the exported labels, and the relocations.
 *
 * A relocation names the place to patch (section and offset), how to patch
 * it (IMM16: the immediate of an instruction, big-endian; ABS16: two data
 * bytes, little-endian), and where the address comes from: a section of
 * this object at an index, or an imported name plus an addend, looked up
 * among the exports of all objects.  Labels that are not exported do not
 * appear in the object.
 */
#ifndef SRA8_OBJ_H
#define SRA8_OBJ_H

#include "util.h"

typedef enum { SEC_CODE, SEC_DATA, SEC_BSS } SecType;
extern const char *const SEC_TYPE_NAMES[3];

typedef struct {
    SecType type;
    char *name;         /* "" for the unnamed section */
    long size;
    uint8_t *data;      /* nullptr for bss */
    long cap;
} Section;

typedef struct {
    char *name;
    int section;
    long offset;
} Export;

typedef enum { R_IMM16, R_ABS16 } RelType;
extern const char *const REL_TYPE_NAMES[2];

typedef struct {
    int section;        /* the place to patch */
    long offset;
    RelType type;
    int target;         /* address from: a section of this object (-1: imported) ... */
    long index;         /* ... at this offset, which may lie outside it */
    char *symbol;       /* or an imported name ... */
    long addend;        /* ... plus this */
} Reloc;

typedef struct {
    char *source;
    VEC(Section) sections;
    VEC(Export) exports;
    VEC(Reloc) relocs;
} Object;

char *section_label(const Section *s);                  /* "code" or "code:name", allocated */
const Export *obj_export(const Object *o, const char *name);
void obj_imports(const Object *o, StrList *out);         /* imported names, in order of first use */
void section_append(Section *s, const uint8_t *data, long n);

char *obj_to_json(const Object *o);
/* On error returns false and sets *err (allocated). */
bool obj_from_json(const char *text, const char *path, Object *o, char **err);
bool obj_read(const char *path, Object *o, char **err);
bool obj_write(const char *path, const Object *o);

void obj_patch(uint8_t *data, long offset, RelType type, long value);

#endif
