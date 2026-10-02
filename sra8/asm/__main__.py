"""sra8-as: assemble one .s file into a relocatable object (.o)."""

from __future__ import annotations

import argparse
import os
import sys

from .. import obj as objfile
from .assembler import assemble
from .listing import listing
from .preprocess import AsmError, preprocess


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sra8-as", description="SRA-8 assembler: .s -> .o")
    ap.add_argument("source")
    ap.add_argument("-o", "--output", help="object file (default: source name with .o)")
    ap.add_argument("-l", "--listing", help="write a listing file")
    ap.add_argument("-Werror", dest="werror", action="store_true", help="treat warnings as errors")
    args = ap.parse_args(argv)

    try:
        lines = preprocess(args.source)
    except AsmError as e:
        print("%s: error: %s" % (e.where, e.msg) if e.where else "error: %s" % e, file=sys.stderr)
        return 1
    obj, errors, warnings, asm = assemble(lines, args.source)
    for w in warnings:
        print("%s" % _tag(w, "warning"), file=sys.stderr)
    for e in errors:
        print("%s" % _tag(e, "error"), file=sys.stderr)
    if errors or (warnings and args.werror):
        return 1

    out = args.output or os.path.splitext(args.source)[0] + ".o"
    objfile.write(out, obj)
    if args.listing:
        with open(args.listing, "w", encoding="utf-8") as f:
            f.write(listing(asm))
    return 0


def _tag(message: str, kind: str) -> str:
    """'file:12: text' -> 'file:12: error: text'."""
    head, sep, rest = message.partition(": ")
    if sep and ":" in head and head.rsplit(":", 1)[1].isdigit():
        return "%s: %s: %s" % (head, kind, rest)
    return "%s: %s" % (kind, message)


if __name__ == "__main__":
    sys.exit(main())
