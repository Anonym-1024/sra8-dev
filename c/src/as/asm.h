/* asm.h -- internals of sra8-as shared by its source files. */
#ifndef SRA8_ASM_H
#define SRA8_ASM_H

#include "../common/isa.h"
#include "../common/obj.h"
#include "../common/util.h"

/* ---- errors ---------------------------------------------------------------- */

/* An assembly error.  `where` (file:line) is filled in by the first handler
 * that knows the location. */
typedef struct {
    char *msg;
    char *where;
} AsmErr;

AsmErr *asm_err(const char *fmt, ...);
void asm_err_locate(AsmErr *e, const char *where);
char *asm_err_str(const AsmErr *e);     /* "where: msg" or "msg", allocated */
void asm_err_free(AsmErr *e);

/* ---- preprocessor ---------------------------------------------------------- */

typedef struct {
    char *path;
    long line;
    char *text;         /* Latin-1 bytes, comment removed, stripped, aliases expanded */
} SrcLine;

typedef VEC(SrcLine) SrcLines;

/* Read path and everything it includes.  Errors are located. */
AsmErr *preprocess(const char *path, SrcLines *out);

/* ---- operands -------------------------------------------------------------- */

typedef enum { OP_REG, OP_IMM, OP_LABEL } OpKind;

typedef struct {
    OpKind kind;
    int n;              /* OP_REG */
    bool pair;
    long long value;    /* OP_IMM */
    char *name;         /* OP_LABEL */
    char dir;           /* OP_LABEL: 0, 'b' or 'f' */
    long long offset;   /* OP_LABEL: the constant after + or - */
} Operand;

AsmErr *unescape(const char *s, size_t n, Str *out);
AsmErr *parse_number(const char *text, long long *out);
AsmErr *parse_operand(const char *text, Operand *op);
AsmErr *parse_label_ref(const char *text, Operand *op);
AsmErr *parse_value(const char *text, Operand *op);
AsmErr *split_operands(const char *text, StrList *out);

/* ---- assembler -------------------------------------------------------------- */

/* The object holds neither the source lines nor the labels that are not
 * exported; the assembler keeps them for its listing. */
typedef struct {
    int section;
    long offset, size;
    char *text;         /* UTF-8 */
    const char *kind;   /* instr | data | res */
} ListLine;

typedef struct {
    char *name;
    int section;
    long offset;
    bool exported;
} ListLabel;

typedef struct {
    Object obj;
    StrList errors;
    StrList warnings;
    VEC(ListLine) lines;
    VEC(ListLabel) labels;
} AsmResult;

void assemble(const SrcLines *lines, const char *source, AsmResult *res);

/* ---- listing ------------------------------------------------------------------ */

char *asm_listing(const AsmResult *r);

#endif
