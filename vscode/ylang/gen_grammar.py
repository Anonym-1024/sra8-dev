#!/usr/bin/env python3
"""Generate the VS Code grammar and configuration of the Y language extension.

Follows the draft syntax of examples/asm/echo.y.  Y is still being
designed, so the word lists below are the place to edit; run ``make vscode``
afterwards.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- word lists: edit these as the language changes --------------------------

CONTROL = ["if", "else", "while", "do", "for", "break", "continue", "return",
           "goto", "switch", "case", "default"]
DECLARATIONS = ["decl", "impl", "var", "type", "internal"]   # decl/impl/var NAME: ...  type NAME = ...
COMPOUND = ["struct", "union", "fn"]                         # struct{...} union{...} fn(...) returns T
OTHER = ["returns", "asm"]
TYPES = ["int8", "int16", "int32", "uint8", "uint16", "uint32", "byte", "char", "bool", "addr"]
CONSTANTS = ["true", "false", "null"]
LOGIC = ["eq", "neq", "gt", "sm", "gte", "sme", "not", "and", "or"]   # shown in bold
PREPROCESSOR = ["INCLUDE", "DEFINE", "IFDEF", "IFNDEF", "ELSE", "ENDIF"]
WORD_LISTS = {"control": CONTROL, "declarations": DECLARATIONS, "compound": COMPOUND,
              "other": OTHER, "types": TYPES, "constants": CONSTANTS, "logic": LOGIC}

LOGIC_SCOPE = "keyword.operator.logical.ylang"

# ---------------------------------------------------------------------------

IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
SCHEMA = "https://raw.githubusercontent.com/martinring/tmlanguage/master/tmlanguage.json"
ESCAPES = r"\\[ntr0\\'\"]"
# type prefixes: *T  [*]T  [n]T  []T, any number of them
PREFIXES = r"(?:\*|\[\*\]|\[[^\[\]]*\])"


def words(ws: list[str]) -> str:
    return r"\b(?:" + "|".join(sorted(ws, key=lambda w: (-len(w), w))) + r")\b"


def type_scopes(first: int) -> dict:
    """Captures of TYPE_TAIL, numbered from `first`."""
    return {str(first): {"name": "storage.type.primitive.ylang"},
            str(first + 1): {"name": "storage.type.compound.ylang"},
            str(first + 2): {"name": "entity.name.type.ylang"}}


def grammar() -> dict:
    # the base of a type: built in | struct, union, fn, type | a named type -- three groups
    tail = r"(?:\b(" + "|".join(sorted(TYPES, key=lambda w: (-len(w), w))) + r")\b|\b(" \
        + "|".join(sorted(COMPOUND + ["type"], key=lambda w: (-len(w), w))) + r")\b|(" + IDENT + r"))"
    prefix_op = {"name": "keyword.operator.type.ylang"}
    return {
        "$schema": SCHEMA,
        "name": "Y",
        "scopeName": "source.ylang",
        "patterns": [{"include": "#" + p} for p in (
            "comment", "preprocessor", "string", "character", "number",
            "declaration", "case", "parameter", "type-after-colon", "returns", "prefixed-type",
            "keyword", "type", "constant", "builtin", "call", "operator", "punctuation")],
        "repository": {
            "comment": {"patterns": [
                {"name": "comment.line.double-slash.ylang", "match": r"//.*$"},
                {"name": "comment.block.ylang", "begin": r"/\*", "end": r"\*/"},
            ]},
            # the text preprocessor: !INCLUDE file, !DEFINE name text, !IFDEF/!IFNDEF name,
            # !ELSE, !ENDIF, and !name for a defined alias
            "preprocessor": {"patterns": [
                {"match": r"^\s*(!INCLUDE)\s+(.*?)\s*(?=//|$)",
                 "captures": {"1": {"name": "keyword.control.directive.include.ylang"},
                              "2": {"name": "string.unquoted.include.ylang"}}},
                {"match": r"^\s*(!(?:DEFINE|IFDEF|IFNDEF))\s+(" + IDENT + ")",
                 "captures": {"1": {"name": "keyword.control.directive.define.ylang"},
                              "2": {"name": "entity.name.function.preprocessor.ylang"}}},
                {"name": "keyword.control.directive.define.ylang", "match": r"!(?:ELSE|ENDIF)\b"},
                {"name": "keyword.control.directive.define.ylang", "match": "!" + IDENT},
            ]},
            "string": {
                "name": "string.quoted.double.ylang",
                "begin": r"\b(s)?(\")",
                "beginCaptures": {"1": {"name": "storage.modifier.static-string.ylang"}},
                "end": "\"",
                "patterns": [{"name": "constant.character.escape.ylang", "match": ESCAPES},
                             {"name": "invalid.illegal.escape.ylang", "match": r"\\."}],
            },
            "character": {"name": "constant.character.ylang", "match": r"'(?:" + ESCAPES + r"|[^'\\])'"},
            "number": {"name": "constant.numeric.ylang",
                       "match": r"\b(?:0[xX][0-9A-Fa-f]+|0[bB][01]+|[0-9]+)[uUlL]*\b"},
            # decl/impl NAME: fn ...   decl NAME: type   decl/var NAME: T   type NAME =   fn NAME(
            "declaration": {"patterns": [
                {"match": r"\b(decl|impl)\s+(" + IDENT + r")\s*(:)(?=\s*fn\b)",
                 "captures": {"1": {"name": "storage.type.declaration.ylang"},
                              "2": {"name": "entity.name.function.ylang"},
                              "3": {"name": "punctuation.separator.type.ylang"}}},
                {"match": r"\b(decl)\s+(" + IDENT + r")\s*(:)(?=\s*type\b)",
                 "captures": {"1": {"name": "storage.type.declaration.ylang"},
                              "2": {"name": "entity.name.type.ylang"},
                              "3": {"name": "punctuation.separator.type.ylang"}}},
                {"match": r"\b(decl|var)\s+(" + IDENT + r")\s*(:)",
                 "captures": {"1": {"name": "storage.type.declaration.ylang"},
                              "2": {"name": "variable.other.declaration.ylang"},
                              "3": {"name": "punctuation.separator.type.ylang"}}},
                {"match": r"\b(type)\s+(" + IDENT + r")\s*(=)",
                 "captures": {"1": {"name": "storage.type.declaration.ylang"},
                              "2": {"name": "entity.name.type.ylang"},
                              "3": {"name": "keyword.operator.assignment.ylang"}}},
                {"match": r"\b(fn)\s+(" + IDENT + ")",
                 "captures": {"1": {"name": "storage.type.compound.ylang"},
                              "2": {"name": "entity.name.function.ylang"}}},
            ]},
            # case X:  default:  -- they swallow the space after ':' so that it
            # does not start a type (see type-after-colon)
            "case": {"patterns": [
                {"match": r"\b(case)\b([^:]*)(:)\s*",
                 "captures": {"1": {"name": "keyword.control.ylang"},
                              "2": {"patterns": [{"include": "#number"}, {"include": "#character"},
                                                 {"include": "#constant"}, {"include": "#preprocessor"}]},
                              "3": {"name": "punctuation.separator.case.ylang"}}},
                {"match": r"\b(default)\s*(:)\s*",
                 "captures": {"1": {"name": "keyword.control.ylang"},
                              "2": {"name": "punctuation.separator.case.ylang"}}},
            ]},
            # name: T  -- parameters of fn(...) and members of struct{...} / union{...}
            "parameter": {"match": r"\b(" + IDENT + r")\s*(:)(?=\s*(?:" + PREFIXES + r"|[A-Za-z_]))",
                          "captures": {"1": {"name": "variable.parameter.ylang"},
                                       "2": {"name": "punctuation.separator.type.ylang"}}},
            # the type right after one of the ':' above, with its prefixes
            "type-after-colon": {"match": r"(?<=:)\s*(" + PREFIXES + r"*)\s*" + tail,
                                 "captures": {"1": prefix_op, **type_scopes(2)}},
            "returns": {"match": r"\b(returns)\b\s*(" + PREFIXES + r"*)\s*" + tail + "?",
                        "captures": {"1": {"name": "keyword.other.returns.ylang"}, "2": prefix_op,
                                     **type_scopes(3)}},
            # *T [*]T [n]T []T anywhere else, e.g. in fn(*user, [*]char) or @as([4]int8, x)
            "prefixed-type": {"match": r"(" + PREFIXES + r"+)" + tail,
                              "captures": {"1": prefix_op, **type_scopes(2)}},
            "keyword": {"patterns": [
                # the logic words: here, before "call", so that "and (" is not a call
                {"name": LOGIC_SCOPE, "match": words(LOGIC)},
                {"name": "keyword.control.ylang", "match": words(CONTROL)},
                {"name": "storage.type.declaration.ylang", "match": words(DECLARATIONS)},
                {"name": "storage.type.compound.ylang", "match": words(COMPOUND)},
                {"name": "keyword.other.ylang", "match": words(OTHER)},
            ]},
            "type": {"name": "storage.type.primitive.ylang", "match": words(TYPES)},
            "constant": {"name": "constant.language.ylang", "match": words(CONSTANTS)},
            "builtin": {"name": "support.function.builtin.ylang", "match": "@" + IDENT},
            "call": {"match": r"\b(" + IDENT + r")\s*(?=\()",
                     "captures": {"1": {"name": "entity.name.function.call.ylang"}}},
            # the operators of the draft: = + - & | ~ << >>  (the logic words are keywords)
            "operator": {"patterns": [
                {"name": "keyword.operator.ylang", "match": r"<<|>>|[-+&|~]"},
                {"name": "keyword.operator.assignment.ylang", "match": "="},
                {"name": "keyword.operator.type.ylang", "match": r"\*"},
            ]},
            "punctuation": {"patterns": [
                {"name": "punctuation.terminator.statement.ylang", "match": ";"},
                {"name": "punctuation.separator.comma.ylang", "match": ","},
                {"name": "punctuation.accessor.ylang", "match": r"\."},
            ]},
        },
    }


LANGUAGE = {
    "comments": {"lineComment": "//", "blockComment": ["/*", "*/"]},
    "brackets": [["{", "}"], ["[", "]"], ["(", ")"]],
    "autoClosingPairs": [
        {"open": "{", "close": "}"}, {"open": "[", "close": "]"}, {"open": "(", "close": ")"},
        {"open": "\"", "close": "\"", "notIn": ["string", "comment"]},
        {"open": "'", "close": "'", "notIn": ["string", "comment"]},
        {"open": "/*", "close": " */", "notIn": ["string"]},
    ],
    "surroundingPairs": [["{", "}"], ["[", "]"], ["(", ")"], ["\"", "\""], ["'", "'"]],
    "indentationRules": {
        "increaseIndentPattern": r"^.*\{[^}\"']*$",
        "decreaseIndentPattern": r"^\s*\}",
    },
    "wordPattern": r"[@!]?[A-Za-z_][A-Za-z0-9_]*|(?:0[xXbB])?[0-9A-Fa-f]+[uUlL]*",
}

PACKAGE = {
    "name": "ylang",
    "displayName": "Y Language",
    "description": "Syntax highlighting for the Y language of the SRA-8 development kit (.y, .yh).",
    "version": "0.1.0",
    "publisher": "sra8-dev",
    "license": "UNLICENSED",
    "engines": {"vscode": "^1.60.0"},
    "categories": ["Programming Languages"],
    "contributes": {
        # the logic operators in bold, whatever the colour theme
        "configurationDefaults": {
            "editor.tokenColorCustomizations": {
                "textMateRules": [{"scope": LOGIC_SCOPE, "settings": {"fontStyle": "bold"}}],
            },
        },
        "languages": [
            {"id": "ylang", "aliases": ["Y", "ylang"], "extensions": [".y", ".yh"],
             "configuration": "./language-configuration.json"},
        ],
        "grammars": [
            {"language": "ylang", "scopeName": "source.ylang", "path": "./syntaxes/ylang.tmLanguage.json"},
        ],
    },
}


def dump(name: str, doc: dict) -> None:
    path = os.path.join(HERE, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main() -> int:
    dump("syntaxes/ylang.tmLanguage.json", grammar())
    dump("language-configuration.json", LANGUAGE)
    dump("package.json", PACKAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
