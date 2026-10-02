#!/usr/bin/env python3
"""Generate the VS Code grammars and configuration of this extension.

The list of mnemonics and condition suffixes comes from ``sra8/isa.py``, so
run this (``make vscode``) whenever the instruction set changes.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from sra8 import isa  # noqa: E402

IDENT = r"[A-Za-z_][A-Za-z0-9_.]*"
NUM_BODY = r"(?:0[xX][0-9A-Fa-f]+|0[bB][01]+|0[oO][0-7]+|0[dD][0-9]+|[0-9]+)\b"
NUM = r"[+-]?" + NUM_BODY
ESCAPES = r"\\[ntr0\\'\"]"
SCHEMA = "https://raw.githubusercontent.com/martinring/tmlanguage/master/tmlanguage.json"
REMOVED = "org|align|balign|global|globl|extern|weak|equ|set|section|text|rodata|incbin|fill|space"


def _alternation(words) -> str:
    """Longest first, so that e.g. 'mova' is tried before 'mov'."""
    return "|".join(sorted(words, key=lambda w: (-len(w), w)))


def asm_grammar() -> dict:
    mnemonics = _alternation(isa.INSTRUCTIONS)
    conditions = _alternation(isa.CONDITIONS)
    return {
        "$schema": SCHEMA,
        "name": "SRA-8 Assembly",
        "scopeName": "source.sra8asm",
        "patterns": [{"include": "#" + p} for p in (
            "comment", "preprocessor", "string", "label-definition", "directive", "mnemonic",
            "register", "label-reference", "immediate", "number", "alias", "invalid-comment")],
        "repository": {
            "comment": {"name": "comment.line.semicolon.sra8asm", "match": ";.*$"},
            "invalid-comment": {"name": "invalid.illegal.comment.sra8asm", "match": r"//.*$|/\*"},
            "preprocessor": {"patterns": [
                {"match": r"^\s*(!DEFINE)\s+([A-Za-z_][A-Za-z0-9_]*)",
                 "captures": {"1": {"name": "keyword.control.directive.define.sra8asm"},
                              "2": {"name": "entity.name.function.preprocessor.sra8asm"}}},
                {"match": r"^\s*(!INCLUDE)\s+([^;]*)",
                 "captures": {"1": {"name": "keyword.control.directive.include.sra8asm"},
                              "2": {"name": "string.unquoted.include.sra8asm"}}},
            ]},
            "alias": {"name": "entity.name.function.preprocessor.sra8asm", "match": r"![A-Za-z_][A-Za-z0-9_]*"},
            "string": {"patterns": [
                {"name": "string.quoted.double.sra8asm", "begin": "\"", "end": "\"",
                 "patterns": [{"name": "constant.character.escape.sra8asm", "match": ESCAPES},
                              {"name": "invalid.illegal.escape.sra8asm", "match": r"\\."}]},
                {"name": "constant.character.sra8asm", "match": r"#?\s*'(?:" + ESCAPES + r"|[^'\\])'"},
            ]},
            "label-definition": {"patterns": [
                {"match": r"(\.l)\s+(" + IDENT + r")\s*(:)",
                 "captures": {"1": {"name": "storage.modifier.local.sra8asm"},
                              "2": {"name": "entity.name.label.local.sra8asm"},
                              "3": {"name": "punctuation.separator.label.sra8asm"}}},
                {"match": r"(?<![=.\w])(" + IDENT + r")\s*(:)",
                 "captures": {"1": {"name": "entity.name.function.label.sra8asm"},
                              "2": {"name": "punctuation.separator.label.sra8asm"}}},
            ]},
            "directive": {"patterns": [
                {"match": r"(\.(?:code|data|bss))\b(?:[ \t]+(" + IDENT + "))?",
                 "captures": {"1": {"name": "keyword.control.section.sra8asm"},
                              "2": {"name": "entity.name.section.sra8asm"}}},
                {"match": r"(\.(?:import|export))\b",
                 "captures": {"1": {"name": "keyword.control.import.sra8asm"}}},
                {"name": "storage.type.directive.sra8asm",
                 "match": r"\.(?:byte|word|dword|qword|addr|ascii|asciz|res)\b"},
                {"name": "invalid.illegal.removed-directive.sra8asm", "match": r"\.(?:" + REMOVED + r")\b"},
                {"name": "storage.modifier.direction.sra8asm", "match": r"\.[bf](?=\s*=)"},
            ]},
            "mnemonic": {
                "name": "keyword.mnemonic.sra8asm",
                "match": r"(?i)\b(?:" + mnemonics + r")(?:\.(?:" + conditions + r"))?\b",
            },
            "register": {"patterns": [
                {"name": "variable.language.register.pair.sra8asm", "match": r"(?i)\br(?:1[0-5]|[0-9])a\b"},
                {"name": "variable.language.register.sra8asm", "match": r"(?i)\br(?:1[0-5]|[0-9])\b"},
            ]},
            "label-reference": {
                "match": r"(=)\s*(" + IDENT + r")(?:\s*([+-])\s*(" + NUM_BODY + "))?",
                "captures": {"1": {"name": "keyword.operator.address.sra8asm"},
                             "2": {"name": "variable.other.label.sra8asm"},
                             "3": {"name": "keyword.operator.arithmetic.sra8asm"},
                             "4": {"name": "constant.numeric.sra8asm"}},
            },
            "immediate": {"name": "constant.numeric.immediate.sra8asm", "match": r"#\s*" + NUM},
            "number": {"name": "constant.numeric.sra8asm", "match": r"(?<![\w.])" + NUM},
        },
    }


def ld_grammar() -> dict:
    def kw(word: str, scope: str, name_scope: str | None = None) -> dict:
        if name_scope is None:
            return {"match": r"^\s*(" + word + r")\b", "captures": {"1": {"name": scope}}}
        return {"match": r"^\s*(" + word + r")\s+(" + IDENT + ")",
                "captures": {"1": {"name": scope}, "2": {"name": name_scope}}}

    return {
        "$schema": SCHEMA,
        "name": "SRA-8 Linker Script",
        "scopeName": "source.sra8ld",
        "patterns": [
            {"name": "comment.line.semicolon.sra8ld", "match": ";.*$"},
            kw("memory", "keyword.control.memory.sra8ld", "entity.name.type.region.sra8ld"),
            kw("place", "keyword.control.place.sra8ld", "entity.name.type.region.sra8ld"),
            kw("end", "keyword.control.end.sra8ld"),
            {"match": r"^\s*(code|data|bss)\b(?:[ \t]+(?:(\*)|(" + IDENT + ")))?",
             "captures": {"1": {"name": "storage.type.section.sra8ld"},
                          "2": {"name": "keyword.operator.wildcard.sra8ld"},
                          "3": {"name": "entity.name.section.sra8ld"}}},
            kw("align", "keyword.other.align.sra8ld"),
            kw("symbol", "keyword.control.symbol.sra8ld", "variable.other.symbol.sra8ld"),
            {"match": r"\b(start|size|last)\b(?:\s+(" + IDENT + "))?",
             "captures": {"1": {"name": "keyword.other.sra8ld"}, "2": {"name": "entity.name.type.region.sra8ld"}}},
            {"name": "keyword.operator.assignment.sra8ld", "match": "="},
            {"name": "constant.numeric.sra8ld", "match": r"\b(?:0[xX][0-9A-Fa-f]+|0[bB][01]+|[0-9]+)\b"},
        ],
    }


LANG_ASM = {
    "comments": {"lineComment": ";"},
    "brackets": [],
    "autoClosingPairs": [{"open": "\"", "close": "\"", "notIn": ["string", "comment"]},
                         {"open": "'", "close": "'", "notIn": ["string", "comment"]}],
    "surroundingPairs": [["\"", "\""], ["'", "'"]],
    "wordPattern": r"![A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_.]*|#?-?(?:0[xXbBoOdD])?[0-9A-Fa-f]+",
}

LANG_LD = {
    "comments": {"lineComment": ";"},
    "brackets": [],
    "folding": {"markers": {"start": r"^\s*place\b", "end": r"^\s*end\b"}},
    "indentationRules": {"increaseIndentPattern": r"^\s*place\b", "decreaseIndentPattern": r"^\s*end\b"},
    "wordPattern": r"[A-Za-z_][A-Za-z0-9_.]*|(?:0[xXbB])?[0-9A-Fa-f]+",
}

PACKAGE = {
    "name": "sra8-lang",
    "displayName": "SRA-8 Assembly and Linker Script",
    "description": "Syntax highlighting for SRA-8 assembly (.s) and sra8-ld linker scripts (.ld).",
    "version": "0.1.0",
    "publisher": "sra8-dev",
    "license": "UNLICENSED",
    "engines": {"vscode": "^1.60.0"},
    "categories": ["Programming Languages"],
    "contributes": {
        "languages": [
            {"id": "sra8-asm", "aliases": ["SRA-8 Assembly", "sra8asm"], "extensions": [".s", ".inc"],
             "configuration": "./language-configuration.asm.json"},
            {"id": "sra8-ld", "aliases": ["SRA-8 Linker Script", "sra8ld"], "extensions": [".ld"],
             "configuration": "./language-configuration.ld.json"},
        ],
        "grammars": [
            {"language": "sra8-asm", "scopeName": "source.sra8asm", "path": "./syntaxes/sra8-asm.tmLanguage.json"},
            {"language": "sra8-ld", "scopeName": "source.sra8ld", "path": "./syntaxes/sra8-ld.tmLanguage.json"},
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
    dump("syntaxes/sra8-asm.tmLanguage.json", asm_grammar())
    dump("syntaxes/sra8-ld.tmLanguage.json", ld_grammar())
    dump("language-configuration.asm.json", LANG_ASM)
    dump("language-configuration.ld.json", LANG_LD)
    dump("package.json", PACKAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
