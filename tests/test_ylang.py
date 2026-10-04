"""The Y compiler ylangc 0.1 (docs/ylangc.md): preprocessor, diagnostics,
static data, and that the output assembles and links."""

import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

from util import EXAMPLES, LDSCRIPTS, ROOT, asm_file

from sra8.ld import layout, script
from sra8.ylang.__main__ import compile_file
from sra8.ylang.errors import YError

TESTS = os.path.join(ROOT, "tests", "y")

# a script with room for programs larger than the 4 KiB boot ROM
BIG = """
memory rom  start 0x0000  size 0xE000
memory ram  start 0xE000  size 0x2000
place rom
    code vector
    code *
    data *
end
place ram
    bss *
end
symbol __stack_top = last ram
"""


def compile_text(text, files=None, **kw):
    with tempfile.TemporaryDirectory() as d:
        for name, content in (files or {}).items():
            with open(os.path.join(d, name), "w") as f:
                f.write(textwrap.dedent(content))
        path = os.path.join(d, "t.y")
        with open(path, "w") as f:
            f.write(textwrap.dedent(text))
        return compile_file(path, **kw)


def error_of(text, **kw):
    try:
        compile_text(text, **kw)
    except YError as e:
        return e.msg
    return None


def assemble_text(asm):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.s")
        with open(path, "w") as f:
            f.write(asm)
        return asm_file(path)


def link(objs, script_text=None):
    sc = script.parse(script_text, "test.ld") if script_text else script.load(os.path.join(LDSCRIPTS, "boot.ld"))
    return layout.link(sc, ["o%d.o" % i for i in range(len(objs))], objs)


def data_bytes(asm, label):
    """The bytes after `label:` in the output, up to the next label."""
    lines = asm.split("\n")
    i = lines.index("%s:" % label)
    out = []
    for line in lines[i + 1:]:
        m = re.match(r"\s+\.byte (.*)", line)
        if m:
            out += [int(x) for x in m.group(1).split(",")]
        elif re.match(r"\s+\.addr", line):
            out.append(line.split()[-1])
        else:
            break
    return out


class Preprocessor(unittest.TestCase):
    def test_define_ifdef_else(self):
        asm = compile_text("""
            !DEFINE A 2
            !IFDEF B
            var x: uint8 = 1;
            !ELSE IFNDEF A
            var x: uint8 = 2;
            !ELSE
            var x: uint8 = !A + 1;   // 3
            !ENDIF
            """)
        self.assertEqual(data_bytes(asm, "x"), [3])

    def test_command_line_define(self):
        asm = compile_text("""
            !IFDEF FAST
            var speed: uint8 = !FAST;
            !ENDIF
            """, defines={"FAST": "9"})
        self.assertEqual(data_bytes(asm, "speed"), [9])

    def test_include_relative_and_guard(self):
        asm = compile_text("""
            !INCLUDE h.yh
            !INCLUDE h.yh
            var y: int16 = K * 2;
            """.replace("K", "!K"), files={"h.yh": """
            !IFNDEF H
            !DEFINE H
            !DEFINE K 21
            !ENDIF
            """})
        self.assertEqual(data_bytes(asm, "y"), [42, 0])

    def test_errors(self):
        self.assertIn("refers to itself", error_of("!DEFINE A !B\n!DEFINE B !A\nvar x: int8 = !A;\n"))
        self.assertIn("already defined", error_of("!DEFINE A 1\n!DEFINE A 2\n"))
        self.assertIn("missing !ENDIF", error_of("!IFDEF A\n"))
        self.assertIn("cannot find", error_of("!INCLUDE nowhere.yh\n"))


class Diagnostics(unittest.TestCase):
    CASES = {
        "var a: int8 = 0;\nimpl f: fn(a: int8) {}\n": "no shadowing",
        "impl f: fn(a: int8, b: int16) returns int16 { return a + b; }\n": "types differ",
        "var x: uint8 = 300;\n": "does not fit in uint8",
        "impl f: fn(a: int8) { var c: bool = a lt 3; }\n": "write @bool",
        "impl f: fn(a: int8) { if (a) { return; } }\n": "a condition is needed",
        "impl f: fn(p: *int8) returns *int8 { return p + 1; }\n": "pointers have no arithmetic",
        "impl f: fn(p: *[4]int8) returns int8 { return p[1]; }\n": "write [p][i]",
        "type s = struct{x: int8};\nimpl f: fn(p: *s) returns int8 { return p.x; }\n": "[p].x",
        "impl g: fn() returns int8 { return 1; }\nimpl f: fn() { g(); }\n": "'_ = …'",
        "impl f: fn() { g(); }\nimpl g: fn() {}\n": "'g' is not declared",
        "decl g: fn(a: int8);\nimpl g: fn(a: int16) {}\n": "declared as fn(int8)",
        "type p = struct{x: int8, y: int8};\nvar v: p = {x = 1};\n": "field y not initialised",
        "var v: [3]int8 = {1, 2};\n": "2 values for an array of 3",
        "var v: [3]int8 = {1, 2, 3};\nimpl f: fn() returns int8 { return v[3]; }\n": "outside 0 ... 2",
        "impl f: fn() { @reg var x: int8 = 0; }\n": "@reg is not supported",
        "impl f: fn() { var x: int8 = undefined; }\n": "globals only",
        "impl f: fn() { break; }\n": "outside a loop",
        "impl g: fn() {}\nvar p: *fn() = @ptr(g);\nimpl f: fn() { [p](); }\n": "called directly",
        "var a: int8 = 1;\nvar b: int8 = a;\n": "must be a constant",
        "impl f: fn(a: int8, n: int8) returns int8 { return a shl n; }\n": "unsigned integer",
        "@main impl a: fn(x: int8) {}\n": "takes no parameters",
        "impl g: fn() {}\nimpl f: fn() { var p: *fn() = g; }\n": "@ptr",
        "decl t: type;\nvar v: t = undefined;\n": "incomplete type",
    }

    def test_rejected_with_a_clear_message(self):
        for src, text in self.CASES.items():
            msg = error_of(src)
            self.assertIsNotNone(msg, src)
            self.assertIn(text, msg, src)

    def test_message_has_position(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "ylangc"), "/dev/null", "-o", "/dev/null"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "bad.y")
            with open(src, "w") as f:
                f.write("var a: int8 = 0;\n\nvar b: uint8 = -1;\n")
            p = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "ylangc"), src],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertIn("bad.y:3: error: the constant -1 does not fit in uint8", p.stderr)


class StaticData(unittest.TestCase):
    def test_constants_and_initialisers(self):
        asm = compile_text("""
            type point = struct{x: int16, y: int16};
            var a: int16 = -2;
            var b: uint32 = 4 * @sizeof(point) + 1;
            var c: [5]uint8 = {1, 2, _};
            var d: point = {y = 0x1234, x = 1};
            var e: [_]char = "Hi";
            var f: *[3]char = s"ok";
            var g: *int16 = @ptr(d.y);
            var h: uint8 = ~0;
            var i: int8 = 7 rol 1;
            var j: bool = true;
            var k: [4]uint8 = undefined;
            """)
        self.assertEqual(data_bytes(asm, "a"), [0xFE, 0xFF])
        self.assertEqual(data_bytes(asm, "b"), [17, 0, 0, 0])
        self.assertEqual(data_bytes(asm, "c"), [1, 2, 2, 2, 2])
        self.assertEqual(data_bytes(asm, "d"), [1, 0, 0x34, 0x12])
        self.assertEqual(data_bytes(asm, "e"), [72, 105, 0])
        self.assertEqual(data_bytes(asm, "f"), ["=str.1"])
        self.assertEqual(data_bytes(asm, "g"), ["=d+2"])
        self.assertEqual(data_bytes(asm, "h"), [255])
        self.assertEqual(data_bytes(asm, "i"), [14])
        self.assertEqual(data_bytes(asm, "j"), [1])
        self.assertIn("k:\n        .res 4", asm)
        self.assertEqual(data_bytes(asm, "str.1"), [111, 107, 0])


class Output(unittest.TestCase):
    def test_linkage(self):
        asm = compile_text("""
            decl used: fn(x: int8);
            decl unused: fn();
            decl shared: int16;
            internal var hidden: int8 = 0;
            impl visible: fn() { used(1); shared = 2; }
            """)
        self.assertIn(".import shared", asm)
        self.assertIn(".import used", asm)
        self.assertNotIn("unused", asm)
        self.assertIn(".export visible", asm)
        self.assertNotIn(".export hidden", asm)
        self.assertNotIn("code vector", asm)          # no @main, no start-up code

    def test_helpers_only_when_used(self):
        plain = compile_text("impl f: fn(a: int16) returns int16 { return a + a; }\n")
        self.assertNotIn("__", plain)
        asm = compile_text("""
            var r: int16 = 0;
            impl f: fn(a: int16, b: int16) returns int16 { return a / b; }
            """)
        self.assertIn("__divs16:", asm)
        self.assertIn("__divu16:", asm)            # needed by __divs16
        self.assertNotIn("__mul16:", asm)
        self.assertNotIn(".export __", asm)

    def test_hello_example_builds_for_the_boot_rom(self):
        asm = compile_file(os.path.join(EXAMPLES, "y", "hello.y"))
        r = assemble_text(asm)
        self.assertEqual(r.errors, [])
        uart = asm_file(os.path.join(EXAMPLES, "y", "uart.s"))
        self.assertEqual(uart.errors, [])
        res = link([r.obj, uart.obj])
        syms = {s.name: s.addr for s in res.symbols}
        self.assertEqual(syms["_start"], 0)
        self.assertLess(len(res.image), 4096)

    def test_feature_program_assembles_and_links(self):
        asm = compile_file(os.path.join(TESTS, "features.y"))
        r = assemble_text(asm)
        self.assertEqual(r.errors, [])
        self.assertEqual(r.warnings, [])
        link([r.obj], BIG)

    def test_tour_compiles_without_reg(self):
        with open(os.path.join(EXAMPLES, "y", "tour.y")) as f:
            text = f.read()
        self.assertIn("@reg is not supported", error_of(text))
        asm = compile_text(text.replace("@reg var", "var"))
        self.assertEqual(assemble_text(asm).errors, [])


if __name__ == "__main__":
    unittest.main()
