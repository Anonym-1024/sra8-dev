/* json.h -- the small JSON subset needed for object files. */
#ifndef SRA8_JSON_H
#define SRA8_JSON_H

#include "util.h"

typedef enum { J_NULL, J_BOOL, J_INT, J_FLOAT, J_STR, J_ARR, J_OBJ } JType;

typedef struct Json Json;
struct Json {
    JType type;
    bool b;
    long long i;
    char *s;        /* J_STR: UTF-8, NUL-terminated */
    size_t n;       /* J_ARR, J_OBJ: number of items */
    Json **items;
    char **keys;    /* J_OBJ */
};

/* Parse a whole document.  On error returns nullptr and sets *err. */
Json *json_parse(const char *text, char **err);
void json_free(Json *j);
const Json *json_get(const Json *obj, const char *key); /* nullptr if absent */

/* Write s as a JSON string the way Python's json.dumps(ensure_ascii=False)
 * does: \" \\ \n \r \t \b \f, other control characters as \u00xx. */
void json_write_str(Str *b, const char *s);

#endif
