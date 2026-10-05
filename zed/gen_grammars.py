#!/usr/bin/env python3
"""Tree-sitter grammars of the Zed extension: SRA-8 assembly, linker scripts, Y.

Zed highlights with Tree-sitter parsers.  This script writes each grammar as
``tree-sitter/<name>/src/grammar.json`` (Tree-sitter's own format, so no
JavaScript runtime is needed), and ``make zed`` turns it into the C parser
with ``tree-sitter generate``.  The highlighting itself is in
``languages/*/highlights.scm``.

Y is still being designed (examples/asm/echo.y): edit the Y rules here and
run ``make zed``.

``gen_grammars.py --manifest`` (``make zed-extension``) writes extension.toml.
Zed builds the grammars from a committed revision of this repository, so it
refuses while zed/tree-sitter has uncommitted changes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- a tiny version of Tree-sitter's grammar DSL ------------------------------
# A string starting with "$" is a rule reference, any other string a literal.


def r(x):
    if isinstance(x, dict):
        return x
    if x.startswith("$"):
        return {"type": "SYMBOL", "name": x[1:]}
    return {"type": "STRING", "value": x}


def seq(*m):
    return {"type": "SEQ", "members": [r(x) for x in m]}


def choice(*m):
    return {"type": "CHOICE", "members": [r(x) for x in m]}


def opt(x):
    return choice(x, {"type": "BLANK"})


def rep(x):
    return {"type": "REPEAT", "content": r(x)}


def rep1(x):
    return {"type": "REPEAT1", "content": r(x)}


def pat(v):
    return {"type": "PATTERN", "value": v}


def field(name, x):
    return {"type": "FIELD", "name": name, "content": r(x)}


def alias(x, name):
    return {"type": "ALIAS", "content": r(x), "named": True, "value": name}


def token(x):
    return {"type": "TOKEN", "content": r(x)}


def immediate(x):
    return {"type": "IMMEDIATE_TOKEN", "content": r(x)}


def prec(n, x):
    return {"type": "PREC", "value": n, "content": r(x)}


def prec_left(n, x):
    return {"type": "PREC_LEFT", "value": n, "content": r(x)}


def prec_right(n, x):
    return {"type": "PREC_RIGHT", "value": n, "content": r(x)}


def comma_sep1(x):
    return seq(x, rep(seq(",", x)))


def comma_sep(x):
    return opt(seq(comma_sep1(x), opt(",")))


def grammar(name, rules, extras, word=None, conflicts=()):
    g = {"name": name, "rules": rules, "extras": [r(e) for e in extras],
         "conflicts": [list(c) for c in conflicts],
         "precedences": [], "externals": [], "inline": [], "supertypes": []}
    if word:
        g["word"] = word
    return g


# ---- SRA-8 assembly (docs/asm.md) -------------------------------------------------
# Line oriented: newlines end statements, so they are not extras.

ASM = grammar("sra8asm", {
    "source_file": seq(rep(seq(opt("$_line"), "$_newline")), opt("$_line")),
    "_newline": pat(r"\r?\n"),
    "_line": choice("$preproc_include", "$preproc_define",
                    seq(rep1(choice("$label", "$local_label")), opt("$_statement")), "$_statement"),
    "label": seq(field("name", "$identifier"), ":"),
    "local_label": seq(".l", field("name", "$identifier"), ":"),
    "_statement": choice("$instruction", "$directive"),
    "instruction": seq(field("mnemonic", "$identifier"), opt(comma_sep1("$_operand"))),
    "directive": seq(field("name", "$directive_name"), opt(comma_sep1("$_argument"))),
    "directive_name": pat(r"\.[a-z]+"),
    "_operand": choice("$register", "$immediate", "$label_ref", "$alias"),
    "_argument": choice("$number", "$char", "$string", "$label_ref", "$immediate", "$alias", "$identifier"),
    "register": pat(r"[rR](1[0-5]|[0-9])[aA]?"),
    "immediate": seq("#", choice("$number", "$char")),
    "label_ref": seq(opt(field("direction", choice(".b", ".f"))), "=", field("name", "$identifier"),
                     opt(seq(choice("+", "-"), "$number"))),
    "number": pat(r"[+-]?(0[bBoOdDxX][0-9A-Fa-f]+|[0-9][0-9A-Fa-f]*)"),
    "char": pat(r"'([^'\\\n]|\\.)'"),
    "string": pat(r'"([^"\\\n]|\\.)*"'),
    "alias": pat(r"![A-Za-z_][A-Za-z0-9_]*"),
    "preproc_include": seq("!INCLUDE", field("path", "$path")),
    "path": pat(r"[^\s;][^\n;]*"),
    "preproc_define": seq("!DEFINE", field("name", "$identifier"), opt(field("value", "$define_value"))),
    "define_value": pat(r"[^\s;][^\n;]*"),
    "identifier": pat(r"[A-Za-z_][A-Za-z0-9_.]*"),
    "comment": pat(r";.*"),
}, extras=[pat(r"[ \t\f]"), "$comment"])

# ---- linker scripts (docs/ld.md) ------------------------------------------------------

LD = grammar("sra8ld", {
    "source_file": rep(choice("$memory", "$place", "$symbol_definition")),
    "memory": seq("memory", field("name", "$identifier"), "start", field("start", "$number"),
                  "size", field("size", "$number")),
    "place": seq("place", field("region", "$identifier"),
                 rep(choice("$section", "$align", "$symbol_here")), "end"),
    "section": prec_right(0, seq(field("type", choice("code", "data", "bss")),
                                 opt(choice(field("name", "$identifier"), "*")))),
    "align": seq("align", "$number"),
    "symbol_here": seq("symbol", field("name", "$identifier")),
    "symbol_definition": seq("symbol", field("name", "$identifier"), "=",
                             choice("$number", seq(choice("start", "last"), field("region", "$identifier")))),
    "number": pat(r"0[xX][0-9A-Fa-f]+|0[bB][01]+|[0-9]+"),
    "identifier": pat(r"[A-Za-z_][A-Za-z0-9_.]*"),
    "comment": pat(r";.*"),
}, extras=[pat(r"\s"), "$comment"], word="identifier")

# ---- Y (docs/y.md) ----------------------------------------------------------------------

Y_TYPES = ["int8", "int16", "int32", "uint8", "uint16", "uint32", "byte", "char", "bool", "addr", "opaque"]
Y_COMPARE = ["eq", "ne", "lt", "le", "gt", "ge"]
Y_BITWISE = ["&", "|", "^", "shl", "shr", "sar", "rol", "ror"]
Y_ASSIGN = ["=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^="]

# docs/y.md 11.2, lowest first
P = {"logic": 1, "not": 2, "compare": 3, "add": 4, "mul": 5, "bit": 6, "prefix": 7, "postfix": 8}


def binary(op, level):
    return prec_left(P[level], seq(field("left", "$_expression"), field("operator", op),
                                   field("right", "$_expression")))


Y = grammar("ylang", {
    "source_file": rep("$_top_level"),
    "_top_level": choice("$declaration", "$type_definition", "$implementation", "$variable_declaration",
                         "$attribute", "$_preproc"),

    # preprocessor (docs/y.md 3)
    "_preproc": choice("$preproc_include", "$preproc_define", "$preproc_conditional", "$preproc_else",
                       "$preproc_endif"),
    "preproc_include": seq("!INCLUDE", field("path", "$path")),
    "path": pat(r"[^\s]+"),
    "preproc_define": seq("!DEFINE", field("name", "$identifier"), opt(field("value", "$macro_value"))),
    "macro_value": immediate(pat(r"[ \t]+[^ \t\r\n][^\r\n]*")),   # the rest of the line
    "preproc_conditional": seq(choice("!IFDEF", "!IFNDEF"), field("name", "$identifier")),
    "preproc_else": seq("!ELSE", opt(seq(choice("IFDEF", "IFNDEF"), field("name", "$identifier")))),
    "preproc_endif": "!ENDIF",
    "alias": pat(r"![A-Za-z_][A-Za-z0-9_]*"),

    # declarations (docs/y.md 7); attributes are items of their own, before what they apply to
    "attribute": choice("@main", "@reg", "@internal", "@recursive", seq("@section", "(", field("name", "$identifier"), ")")),
    "declaration": seq("decl", field("name", "$identifier"), ":", field("type", choice("$_type", "type")), ";"),
    "type_definition": seq("type", field("name", "$identifier"), "=", field("value", "$_type"), ";"),
    "implementation": seq("impl", field("name", "$identifier"), ":",
                          field("type", "$function_type"), field("body", "$block")),
    "variable_declaration": seq("var", field("name", "$identifier"), ":",
                                field("type", "$_type"), "=", field("value", choice("$_value", "undefined")), ";"),

    # types: prefixes, read left to right (docs/y.md 5.8)
    "_type": choice("$primitive_type", alias("$identifier", "type_identifier"), "$pointer_type",
                    "$many_pointer_type", "$array_type", "$struct_type", "$union_type", "$function_type"),
    "primitive_type": choice(*Y_TYPES),
    "pointer_type": seq("*", field("element", "$_type")),
    "many_pointer_type": seq("[", "*", "]", field("element", "$_type")),
    "array_type": seq("[", field("length", choice("$_expression", "_")), "]", field("element", "$_type")),
    "struct_type": seq("struct", "$field_list"),
    "union_type": seq("union", "$field_list"),
    "field_list": seq("{", comma_sep1("$field_declaration"), opt(","), "}"),
    "field_declaration": seq(field("name", "$identifier"), ":", field("type", "$_type")),
    "function_type": prec_right(0, seq("fn", "$parameter_list",
                                       opt(seq("returns", field("return_type", "$_type"))))),
    "parameter_list": seq("(", comma_sep("$parameter"), ")"),
    "parameter": choice(seq(field("name", "$identifier"), ":", field("type", "$_type")), field("type", "$_type")),

    # statements (docs/y.md 10)
    "block": seq("{", rep("$_statement"), "}"),
    "_statement": choice("$variable_declaration", "$attribute", "$assignment_statement", "$call_statement",
                         "$discard_statement", "$if_statement", "$loop_statement", "$break_statement",
                         "$continue_statement", "$return_statement", "$block", "$_preproc"),
    "assignment_statement": seq(field("left", "$_expression"), field("operator", choice(*Y_ASSIGN)),
                                field("right", "$_value"), ";"),
    "call_statement": seq("$call_expression", ";"),
    "discard_statement": seq("_", "=", field("value", "$_expression"), ";"),
    "if_statement": seq("if", "(", field("condition", "$_expression"), ")", field("consequence", "$block"),
                        opt(seq("else", field("alternative", choice("$if_statement", "$block"))))),
    "loop_statement": seq("loop", opt(field("name", "$identifier")), field("body", "$block")),
    "break_statement": seq("break", opt(field("label", "$identifier")), ";"),
    "continue_statement": seq("continue", opt(field("label", "$identifier")), ";"),
    "return_statement": seq("return", opt("$_value"), ";"),

    # initialisers (docs/y.md 9)
    "_value": choice("$_expression", "$initializer"),
    "initializer": seq("{", choice(
        seq("$_value", rep(seq(",", "$_value")), opt(seq(",", "$fill"))),
        comma_sep1("$field_initializer")), opt(","), "}"),
    "fill": "_",
    "field_initializer": seq(field("name", "$identifier"), "=", field("value", "$_value")),

    # expressions (docs/y.md 11)
    "_expression": choice("$binary_expression", "$unary_expression", "$cast_expression", "$call_expression",
                          "$index_expression", "$member_expression", "$dereference_expression",
                          "$builtin_expression", "$parenthesized_expression", "$identifier", "$number",
                          "$char", "$string", "$static_string", "$true", "$false", "$nullptr", "$alias"),
    "binary_expression": choice(
        binary(choice("and", "or"), "logic"), binary(choice(*Y_COMPARE), "compare"),
        binary(choice("+", "-"), "add"), binary(choice("*", "/", "%"), "mul"),
        binary(choice(*Y_BITWISE), "bit")),
    "unary_expression": choice(
        prec(P["not"], seq(field("operator", "not"), field("operand", "$_expression"))),
        prec(P["prefix"], seq(field("operator", choice("-", "~")), field("operand", "$_expression")))),
    "cast_expression": seq(field("operator", choice("@as", "@cast")), "(", field("type", "$_type"), ",",
                           field("operand", "$_expression"), ")"),
    "call_expression": prec(P["postfix"], seq(field("function", "$_expression"), "$argument_list")),
    "argument_list": seq("(", comma_sep("$_value"), ")"),
    "index_expression": prec(P["postfix"], seq(field("object", "$_expression"), "[",
                                               field("index", "$_expression"), "]")),
    "member_expression": prec(P["postfix"], seq(field("object", "$_expression"), ".",
                                                field("field", "$identifier"))),
    "dereference_expression": seq("[", field("pointer", "$_expression"), "]"),
    "builtin_expression": choice(seq("@ptr", "(", field("operand", "$_expression"), ")"),
                                 seq("@bool", "(", field("operand", "$_expression"), ")"),
                                 seq("@sizeof", "(", field("type", "$_type"), ")")),
    "parenthesized_expression": seq("(", "$_expression", ")"),

    # literals (docs/y.md 4)
    "number": pat(r"0[xX][0-9A-Fa-f]+|0[bB][01]+|0[oO][0-7]+|0[dD][0-9]+|[0-9]+"),
    "char": pat(r"'([^'\\\n]|\\.)'"),
    "string": pat(r'"([^"\\\n]|\\.)*"'),
    "static_string": pat(r's"([^"\\\n]|\\.)*"'),
    "true": "true",
    "false": "false",
    "nullptr": "nullptr",
    "identifier": pat(r"[A-Za-z_][A-Za-z0-9_]*"),
    "comment": token(choice(pat(r"//[^\n]*"), pat(r"/\*[^*]*\*+([^/*][^*]*\*+)*/"))),
}, extras=[pat(r"\s"), "$comment"], word="identifier")

GRAMMARS = {"sra8asm": ASM, "sra8ld": LD, "ylang": Y}


MANIFEST = """\
# Written by `make zed-extension`: the repository path and revision are of
# this checkout.  Not committed.
id = "sra8"
name = "SRA-8"
version = "0.1.0"
schema_version = 1
authors = ["SRA-8 development kit"]
description = "SRA-8 assembly, sra8-ld linker scripts and the Y language."
"""


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=HERE, check=True, capture_output=True, text=True).stdout.strip()


def manifest() -> int:
    root = git("rev-parse", "--show-toplevel")
    dirty = git("status", "--porcelain", "--", "tree-sitter")
    if dirty:
        print("zed/tree-sitter has uncommitted changes; commit them first, because Zed\n"
              "builds the grammars from a committed revision:\n" + dirty, file=sys.stderr)
        return 1
    rev = git("rev-parse", "HEAD")
    text = MANIFEST
    for name in GRAMMARS:
        text += '\n[grammars.%s]\nrepository = "file://%s"\nrev = "%s"\npath = "zed/tree-sitter/%s"\n' % (
            name, root, rev, name)
    with open(os.path.join(HERE, "extension.toml"), "w") as f:
        f.write(text)
    print("wrote zed/extension.toml for revision %s" % rev[:12])
    return 0


def main() -> int:
    if sys.argv[1:] == ["--manifest"]:
        return manifest()
    for name, g in GRAMMARS.items():
        for k, v in list(g["rules"].items()):
            g["rules"][k] = r(v)
        d = os.path.join(HERE, "tree-sitter", name, "src")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "grammar.json"), "w") as f:
            json.dump(g, f, indent=2)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
