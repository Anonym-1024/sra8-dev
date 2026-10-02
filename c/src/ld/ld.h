/* ld.h -- internals of sra8-ld shared by its source files. */
#ifndef SRA8_LD_H
#define SRA8_LD_H

#include "../common/isa.h"
#include "../common/obj.h"
#include "../common/util.h"

/* ---- linker script (spec 5.2, docs/ld.md) --------------------------------- */

typedef struct {
    char *name;
    long start, size;
    char *where;
} Region;

typedef enum { PI_SECTION, PI_ALIGN, PI_SYMBOL } PlaceKind;

typedef struct {
    PlaceKind kind;
    char *where;
    SecType stype;      /* PI_SECTION */
    char *name;         /* PI_SECTION: nullptr = unnamed, "*" = all remaining; PI_SYMBOL: the name */
    long value;         /* PI_ALIGN */
} PlaceItem;

typedef struct {
    char *region;
    char *where;
    VEC(PlaceItem) items;
} Place;

typedef enum { SS_NUMBER, SS_START, SS_LAST } ScriptSymKind;

typedef struct {
    char *name;
    ScriptSymKind kind;
    char *where;
    long value;
    char *region;
} ScriptSym;

typedef struct {
    char *path;
    VEC(Region) regions;
    VEC(Place) places;
    VEC(ScriptSym) symbols;
} Script;

/* On error returns false and sets *err. */
bool script_parse(const char *text, const char *path, Script *s, char **err);
bool script_load(const char *path, Script *s, char **err);
const Region *script_region(const Script *s, const char *name);

/* ---- the link -------------------------------------------------------------------- */

typedef struct {
    int obj, sec;
    SecType stype;
    char *name;
    long addr, size;
    uint8_t *data;      /* nullptr for bss */
} Contribution;

typedef enum { LS_EXPORTED, LS_SCRIPT } LinkedKind;

typedef struct {
    char *name;
    long addr;
    LinkedKind kind;
    int obj;            /* -1 for script symbols */
} LinkedSymbol;

typedef struct {
    char *name;
    long start, size, used;
} RegionUse;

typedef struct {
    char **paths;
    Object *objects;
    size_t nobj;
    VEC(Contribution) contribs;     /* sorted by address */
    VEC(LinkedSymbol) symbols;
    VEC(RegionUse) regions;
    long image_start;
    uint8_t *image;
    long image_len;
    long **base;        /* base[obj][sec], -1 when not placed */
} LinkResult;

/* On error returns false and fills errors. */
bool link_objects(const Script *s, char **paths, Object *objects, size_t nobj, LinkResult *res, StrList *errors);

/* ---- outputs ------------------------------------------------------------------------ */

char *mem_text(const LinkResult *r, long mem_size, char **err);
char *ihex_text(const LinkResult *r);
char *map_text(const LinkResult *r, const char *script_path);

#endif
