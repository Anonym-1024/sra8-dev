"""sra8-ld: link objects into an image, driven by a linker script."""

from __future__ import annotations

import argparse
import os
import sys

from .. import obj as objfile
from .layout import LinkError, link
from .output import OutputError, ihex_text, map_text, mem_text
from .script import ScriptError, load

# sra8/ld/__main__.py -> the repository root, two levels up
_REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DEFAULT_SCRIPT = os.path.join(_REPO, "ldscripts", "boot.ld")
EXTENSIONS = {"bin": ".bin", "mem": ".mem", "ihex": ".hex"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sra8-ld", description="SRA-8 linker: objects + script -> image")
    ap.add_argument("objects", nargs="+", help="object files, linked in this order")
    ap.add_argument("-T", "--script", default=DEFAULT_SCRIPT, help="linker script (default: ldscripts/boot.ld)")
    ap.add_argument("-o", "--output", help="output file (default: a.bin, a.mem or a.hex)")
    ap.add_argument("--format", choices=("bin", "mem", "ihex"), default="bin")
    ap.add_argument("--mem-size", type=lambda s: int(s, 0), default=4096,
                    help="bytes in a .mem image (default 4096, the boot ROM)")
    ap.add_argument("-M", "--map", help="write a map file")
    args = ap.parse_args(argv)

    try:
        script = load(args.script)
        objects = [objfile.read(p) for p in args.objects]
        res = link(script, args.objects, objects)
        if args.format == "mem":
            content: str | bytes = mem_text(res, args.mem_size)
        elif args.format == "ihex":
            content = ihex_text(res)
        else:
            content = res.image
    except LinkError as e:
        for m in e.errors:
            print("error: %s" % m, file=sys.stderr)
        return 1
    except (ScriptError, objfile.ObjError, OutputError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1

    out = args.output or "a" + EXTENSIONS[args.format]
    if isinstance(content, bytes):
        with open(out, "wb") as f:
            f.write(content)
    else:
        with open(out, "w", encoding="utf-8") as f:
            f.write(content)
    if args.map:
        with open(args.map, "w", encoding="utf-8") as f:
            f.write(map_text(res, args.script))
    return 0


if __name__ == "__main__":
    sys.exit(main())
