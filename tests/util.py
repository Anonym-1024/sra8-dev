"""Helpers shared by the tests: assemble and link from strings, in process."""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sra8.asm.assembler import assemble  # noqa: E402
from sra8.asm.preprocess import AsmError, preprocess  # noqa: E402
from sra8.ld import layout, script  # noqa: E402
from sra8.obj import Object  # noqa: E402

RTL = os.environ.get("SRA8_RTL", os.path.join(ROOT, "..", "sra-8-fpga", "sra-8-fpga"))
GOLDEN = os.path.join(ROOT, "tests", "golden")
EXAMPLES = os.path.join(ROOT, "examples")
LDSCRIPTS = os.path.join(ROOT, "ldscripts")

FLAT = """
memory all start 0x0000 size 0x10000
place all
    code *
    data *
    bss *
end
"""


class AsmResult:
    def __init__(self, obj: Object, errors: list[str], warnings: list[str]) -> None:
        self.obj = obj
        self.errors = errors
        self.warnings = warnings


def asm_file(path: str) -> AsmResult:
    try:
        lines = preprocess(path)
    except AsmError as e:
        return AsmResult(Object(path), [str(e)], [])
    return AsmResult(*assemble(lines, path)[:3])


def asm_text(text: str, name: str = "t.s", extra: dict[str, str] | None = None) -> AsmResult:
    with tempfile.TemporaryDirectory() as d:
        for fname, content in (extra or {}).items():
            with open(os.path.join(d, fname), "w") as f:
                f.write(textwrap.dedent(content))
        path = os.path.join(d, name)
        with open(path, "w") as f:
            f.write(textwrap.dedent(text))
        res = asm_file(path)
        res.obj.source = name
        return res


def asm_ok(text: str, **kw) -> Object:
    r = asm_text(text, **kw)
    if r.errors:
        raise AssertionError("unexpected errors: %s" % r.errors)
    return r.obj


def link_objs(objs: list[Object], script_text: str = FLAT, names: list[str] | None = None) -> layout.Result:
    names = names or ["o%d.o" % i for i in range(len(objs))]
    return layout.link(script.parse(textwrap.dedent(script_text), "test.ld"), names, objs)


def link_errors(objs: list[Object], script_text: str = FLAT) -> list[str]:
    try:
        link_objs(objs, script_text)
    except layout.LinkError as e:
        return e.errors
    return []
