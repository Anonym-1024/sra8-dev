"""The Y compiler ylangc 0.4 (docs/ylangc.md): preprocessor, diagnostics,
static data, ABI 0.4 static and stack frames, the size optimisations, and
that the output assembles and links."""

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
    symbol __bss_start
    bss *
    symbol __bss_end
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
        "@recursive decl g: fn();\nimpl g: fn() { }\n": "not @recursive here but is in its decl",
        "@recursive var x: int8 = 0;\n": "functions only",
        "@internal decl g: fn();\n": "@internal applies to",
        "impl f: fn() { var x: int8 = undefined; }\n": "globals only",
        "impl f: fn() { break; }\n": "outside a loop",
        "impl g: fn() {}\nvar p: *fn() = @ptr(g);\nimpl f: fn() { [p](); }\n": "called directly",
        "var a: int8 = 1;\nvar b: int8 = a;\n": "must be a constant",
        "impl f: fn(a: int8, n: int8) returns int8 { return a shl n; }\n": "unsigned integer",
        "@main impl a: fn(x: int8) {}\n": "takes no parameters",
        "impl g: fn() {}\nimpl f: fn() { var p: *fn() = g; }\n": "@ptr",
        "decl t: type;\nvar v: t = undefined;\n": "incomplete type",
    }

    def test_recursion_is_not_checked(self):
        # re-entering a function that is not @recursive is the programmer's
        # responsibility (ABI 0.3): it compiles
        self.assertIsNone(error_of("impl f: fn(n: uint8) { if (n ne 0) { f(n - 1); } }\n"))
        self.assertIsNone(error_of("decl g: fn();\nimpl f: fn() { g(); }\nimpl g: fn() { f(); }\n"))

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
            decl pointed: fn();
            @internal var hidden: int8 = 0;
            @internal impl helper: fn() { }
            impl visible: fn() { used(1); shared = 2; var p: *fn() = @ptr(pointed); helper(); }
            """)
        self.assertIn(".import shared", asm)
        self.assertIn(".import used\n", asm)
        self.assertIn(".import used.frame", asm)       # arguments go to the callee's frame
        self.assertIn(".import pointed\n", asm)
        self.assertNotIn("pointed.frame", asm)          # only its address is taken
        self.assertNotIn("unused", asm)
        self.assertIn(".export visible\n", asm)
        self.assertIn(".export visible.frame", asm)
        self.assertNotIn(".export hidden", asm)
        self.assertNotIn(".export helper", asm)
        self.assertNotIn("code vector", asm)          # no @main, no start-up code

    def test_recursive_functions_have_no_static_frame(self):
        asm = compile_text("""
            @recursive decl r: fn(x: int8);
            @recursive impl own: fn(x: int8) { r(x); }
            """)
        self.assertIn(".import r\n", asm)
        self.assertNotIn("r.frame", asm)               # arguments go to the stack
        self.assertIn(".export own\n", asm)
        self.assertNotIn("own.frame", asm)
        self.assertRegex(asm, r"\.addr   0 .*\n\s+\.dword  \d+ .*\nown:")

    def test_static_frames(self):
        asm = compile_text("""
            impl add: fn(a: int16, b: int16) returns int16 { return a + b; }
            """)
        # header before the entry: frame address and size (result 2, a 2, b 2, saved r12a 2)
        self.assertRegex(asm, r"\.addr   =add\.frame .*\n\s+\.dword  8 .*\nadd:")
        self.assertIn("ldr     r0, =add.frame+2", asm)     # a, one instruction
        self.assertIn("str     r0, =add.frame ", asm)      # the result
        self.assertIn("add.frame:\n        .res 8", asm)
        self.assertNotIn("r14", asm)                       # no stack use without recursion

    def test_recursive_functions_use_a_stack_frame(self):
        asm = compile_text("""
            @recursive impl f: fn(n: uint8) returns uint8 {
                if (n eq 0) { return 0; }
                return f(n - 1) + 1;
            }
            """)
        self.assertRegex(asm, r"\.addr   0 .*\n\s+\.dword  2 .*\nf:")
        self.assertIn("lea     r14a, r14a, #-2", asm)    # prologue: the frame (the return address)
        self.assertIn("sto     r12, r14a, #1", asm)      # the return address
        self.assertIn("ldo     r0, r14a, #4", asm)       # n, in the caller's area
        self.assertIn("ldo     r0, r14a, #6", asm)       # ... read below the call's area
        self.assertIn("sto     r0, r14a, #2", asm)       # the argument, straight into the area
        self.assertIn("ldo     r0, r14a, #1", asm)       # the callee's result
        self.assertIn("lea     r14a, r14a, #2", asm)     # epilogue
        self.assertNotIn("ldr ", asm)
        self.assertNotIn("str ", asm)

    def test_indirect_calls_dispatch_on_the_header(self):
        asm = compile_text("""
            impl call: fn(f: *fn(x: int8) returns int8, v: int8) returns int8 { return f(v); }
            """)
        # the header at the function - 4: its static frame, or 0 when @recursive
        m = re.search(r"ldo     (r\d), r10a, #-4 .*\n\s+ldo     (r\d), r10a, #-3", asm)
        self.assertIsNotNone(m)
        self.assertIn("ord     %s, %s" % m.groups(), asm)
        self.assertIn("brl     r12a, r10a", asm)
        self.assertIn("lea     r14a, r14a, #-2", asm)     # the stack path

    def test_large_stack_frames_use_far_offsets(self):
        asm = compile_text("""
            @recursive impl f: fn(n: uint8) returns uint8 {
                var buf: [3000]uint8 = {0, _};
                buf[2999] = n;
                if (n ne 0) { _ = f(n - 1); }
                return buf[2999];
            }
            """)
        self.assertRegex(asm, r"mova    r10a, #\d{4}")
        self.assertIn("lea     r10a, r14a, r10a", asm)

    def test_helpers_only_when_used(self):
        plain = compile_text("impl f: fn(a: int16) returns int16 { return a + a; }\n")
        self.assertNotIn("__", plain)
        asm = compile_text("""
            var r: int16 = 0;
            impl f: fn(a: int16, b: int16) returns int16 { return a / b; }
            """)
        self.assertIn("__divmods16:", asm)         # / and % share one routine
        self.assertNotIn("__divmodu16:", asm)
        self.assertNotIn("__mul16:", asm)
        self.assertNotIn(".export __", asm)
        self.assertNotIn(".addr   =__", asm)        # helpers have no header

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

    def test_leaf_functions_keep_r12a(self):
        asm = compile_text("""
            impl leaf: fn(a: int8) returns int8 { return a + 1; }
            impl caller: fn() returns int8 { return leaf(2); }
            """)
        leaf = asm[asm.index("\nleaf:"):asm.index("\ncaller:")]
        code = "\n".join(l.split(";")[0] for l in leaf.split("\n"))
        self.assertNotIn("r12", code.replace("br      r12a", ""))
        self.assertIn("str     r12, =caller.frame", asm)

    def test_header_only_when_needed(self):
        asm = compile_text("""
            @internal impl hidden: fn() { }
            @internal impl pointed: fn() { }
            impl visible: fn() { hidden(); var p: *fn() = @ptr(pointed); }
            """)
        self.assertNotIn("=hidden.frame ", asm.split("hidden:")[0][-200:])
        self.assertRegex(asm, r"\.addr   =pointed\.frame .*\n.*\npointed:")
        self.assertRegex(asm, r"\.addr   =visible\.frame .*\n.*\nvisible:")
        self.assertNotRegex(asm, r"\.addr   =hidden\.frame")

    def test_zero_globals_in_bss_and_zeroed_at_start(self):
        asm = compile_text("""
            var zeros: [64]char = {0, _};
            var some: [2]uint8 = {0, 1};
            @main impl m: fn() { }
            """)
        self.assertIn("zeros:", asm.split("        .bss\n")[1])
        self.assertIn("some:", asm.split("        .data\n")[1].split("        .bss\n")[0])
        self.assertIn("mova    r2a, =__bss_start", asm)
        self.assertIn("sti     r0, r2a, #1", asm)

    def test_constant_operands_need_no_helper(self):
        asm = compile_text("""
            impl f: fn(a: uint16) returns uint16 { return a * 10 + a / 4 + a % 8 + 3 * a; }
            """)
        self.assertNotIn("__", asm)
        self.assertIn("and     r1, r1, #7", asm.replace("r0, r0, #7", "r1, r1, #7").replace("r2, r2, #7", "r1, r1, #7"))
        signed = compile_text("impl f: fn(a: int16) returns int16 { return a / 4; }\n")
        self.assertIn("__divmods16", signed)     # rounds toward 0: not a shift

    def test_register_offset_indexing(self):
        asm = compile_text("""
            var buf: [8]uint8 = {1, _};
            impl get: fn(p: [*]uint8, i: uint16) returns uint8 { return p[i]; }
            impl put: fn(i: uint16, v: uint8) { buf[i] = v; }
            impl get16: fn(p: [*]uint16, i: uint16) returns uint16 { return p[i]; }
            """)
        self.assertIn("ldr     r10, =get.frame+1", asm)      # the pointer straight into r10a
        self.assertRegex(asm, r"ldo     r\d, r10a, r\da")
        self.assertIn("mova    r10a, =buf", asm)
        self.assertRegex(asm, r"sto     r\d, r10a, r\da")
        self.assertRegex(asm, r"lea     r10a, r10a, r\da")   # 2 bytes: + index, then #0 and #1

    def test_arguments_go_straight_to_the_frame(self):
        asm = compile_text("""
            impl g: fn(a: int16, b: int16) returns int16 { return a - b; }
            impl f: fn(x: int16) returns int16 { return g(x + 1, x); }
            """)
        self.assertNotRegex(asm, r"; (spill|reload) (?!the return address)")

    def test_branches_are_cleaned_up(self):
        asm = compile_text("""
            impl f: fn(n: uint8) returns uint8 {
                var i: uint8 = 0;
                loop { if (i eq n) { break; } i += 1; }
                return i;
            }
            """)
        body = asm[asm.index("\nf:"):]
        self.assertEqual(body.count("br "), 2)        # back to the loop, and `br r12a`
        self.assertEqual(body.count("br."), 1)        # the break: one conditional branch
        self.assertEqual(body.count("; line 4"), 2)   # the loop, and i += 1: no repeats

    def test_test_programs_assemble_and_link(self):
        for name in ("features.y", "recursion.y", "stackframes.y", "indexing.y"):
            asm = compile_file(os.path.join(TESTS, name))
            r = assemble_text(asm)
            self.assertEqual(r.errors, [], name)
            self.assertEqual(r.warnings, [], name)
            link([r.obj], BIG)

    def test_tour_compiles_without_reg(self):
        with open(os.path.join(EXAMPLES, "y", "tour.y")) as f:
            text = f.read()
        self.assertIn("@reg is not supported", error_of(text))
        asm = compile_text(text.replace("@reg var", "var"))
        self.assertEqual(assemble_text(asm).errors, [])


if __name__ == "__main__":
    unittest.main()
