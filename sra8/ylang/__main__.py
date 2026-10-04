"""ylangc: compile one Y file (.y) into SRA-8 assembly (.s)."""

from __future__ import annotations

import argparse
import os
import sys

from . import VERSION
from .compiler import Module
from .errors import YError
from .lexer import tokenize
from .parser import parse
from .preprocess import preprocess


def compile_file(path: str, include_dirs: list[str] | None = None,
                 defines: dict[str, str] | None = None) -> str:
    """Compile the Y file at path; returns the assembly text or raises YError."""
    lines = preprocess(path, include_dirs, defines)
    items = parse(tokenize(lines))
    return Module(lines).compile(items)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ylangc", description="Y compiler %s: .y -> .s" % VERSION)
    ap.add_argument("source")
    ap.add_argument("-o", "--output", help="assembly file (default: source name with .s)")
    ap.add_argument("-I", dest="include", action="append", default=[], metavar="DIR",
                    help="search DIR for !INCLUDE files")
    ap.add_argument("-D", dest="define", action="append", default=[], metavar="NAME[=TEXT]",
                    help="define the alias !NAME")
    args = ap.parse_args(argv)
    defines = {}
    for d in args.define:
        name, _, text = d.partition("=")
        defines[name] = text
    try:
        text = compile_file(args.source, args.include, defines)
    except YError as e:
        print(e, file=sys.stderr)
        return 1
    out = args.output or os.path.splitext(args.source)[0] + ".s"
    with open(out, "w", encoding="latin-1") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
