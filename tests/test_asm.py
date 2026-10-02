"""Assembler behaviour and diagnostics (spec Section 3; Section 10, item 4)."""

import unittest

from util import asm_ok, asm_text, link_objs


def errors(src, **kw):
    return " | ".join(asm_text(src, **kw).errors)


class Sections(unittest.TestCase):
    def test_types_and_names(self):
        o = asm_ok("""
            nop_label: mov r0, #0
            .data
            d: .byte 1
            .code vector
            v: mov r1, #1
            .data rodata
            .asciz "x"
            .bss
            b: .res 10
            .code
            mov r2, #2
        """)
        self.assertEqual([(s.type, s.name, s.size) for s in o.sections],
                         [("code", "", 8), ("data", "", 1), ("code", "vector", 4), ("data", "rodata", 2), ("bss", "", 10)])
        self.assertIsNone(o.sections[4].data)

    def test_no_implicit_empty_section(self):
        o = asm_ok(".data\n.byte 1\n")
        self.assertEqual([s.type for s in o.sections], ["data"])

    def test_instruction_in_data(self):
        self.assertIn("instruction in a .data section", errors(".data\nmov r0, #0\n"))

    def test_bss_only_res(self):
        self.assertIn("only .res", errors(".bss\n.byte 1\n"))
        self.assertIn("instruction in a .bss", errors(".bss\nmov r0, #0\n"))

    def test_unaligned_instruction(self):
        self.assertIn("unaligned offset 1", errors(".code\n.byte 1\nmov r0, #0\n"))
        asm_ok(".code\n.byte 1, 2, 3, 4\nmov r0, #0\n")

    def test_bad_section_name(self):
        self.assertIn("optional section name", errors(".code a b\n"))


class Removed(unittest.TestCase):
    def test_removed_directives(self):
        for d, hint in ((".org 0", "linker script"), (".align 4", "linker script"), (".global x", ".export"),
                        (".extern x", ".import"), (".weak x", "weak"), (".equ X, 1", "!DEFINE"),
                        (".set X, 1", "!DEFINE"), (".section .text", ".code"), (".incbin \"f\"", "not supported"),
                        (".text", ".code")):
            with self.subTest(d):
                e = errors(d + "\n")
                self.assertIn("does not exist", e)
                self.assertIn(hint, e)

    def test_no_pseudo_instructions(self):
        for p in ("nop", "ret r12a", "halt", "movs r1, r2", "mvn r1, r2"):
            self.assertIn("not an SRA-8 instruction", errors(p + "\n"), p)

    def test_only_semicolon_comments(self):
        self.assertIn("only ';' starts a comment", errors("mov r0, #0 // no\n"))
        self.assertIn("only ';' starts a comment", errors("/* no */\n"))
        asm_ok('.data\n.asciz "a // b ; c"   ; fine\n')

    def test_no_expressions(self):
        self.assertIn("expressions are not supported", errors("mov r0, #1+2\n"))
        self.assertIn("bad label reference", errors(".import a\nmova r0a, =a * 2\n"))
        self.assertIn("bad operand", errors("br .\n"))

    def test_no_new_preprocessor_directives(self):
        self.assertIn("unknown preprocessor directive", errors("!IFDEF X\n"))


class Linkage(unittest.TestCase):
    def test_undefined_without_import(self):
        e = errors("br =elsewhere\n")
        self.assertIn("undefined name 'elsewhere'", e)
        self.assertIn(".import elsewhere", e)

    def test_import_used(self):
        o = asm_ok(".import f\nbrl r12a, =f + 4\n")
        self.assertEqual(o.imports(), ["f"])
        r = o.relocations[0]
        self.assertEqual((r.type, r.symbol, r.addend, r.target), ("IMM16", "f", 4, None))
        self.assertEqual(bytes(o.sections[0].data), bytes([0x06, 0xBC, 0x00, 0x04]))

    def test_unused_import_warns(self):
        r = asm_text(".import f\nmov r0, #0\n")
        self.assertFalse(r.errors)
        self.assertIn("never used", " ".join(r.warnings))
        self.assertEqual(r.obj.imports(), [])

    def test_import_and_define(self):
        self.assertIn("imported but also defined", errors(".import f\nf: br =f\n"))

    def test_export(self):
        o = asm_ok(".export f\nf: br =f\ng: br =g\n")
        self.assertEqual([(e.name, e.section, e.offset) for e in o.exports], [("f", 0, 0)])
        self.assertEqual([(r.symbol, r.target, r.index) for r in o.relocations], [(None, 0, 0), (None, 0, 4)])
        self.assertIn("not defined", errors(".export nothing\n"))
        self.assertIn("cannot be exported", errors(".import a\n.export a\nbr =a\n"))
        self.assertIn("local labels cannot be exported", errors(".export x\n.l x: br .b =x\n"))

    def test_duplicate_label(self):
        self.assertIn("already defined", errors("a: mov r0, #0\na: mov r0, #0\n"))


class Operands(unittest.TestCase):
    def test_local_labels(self):
        o = asm_ok("""
            .l x: mov r0, #0
            br .b =x
            br .f =x
            .l x: br .b =x
        """)
        targets = [(r.target, r.index) for r in o.relocations]
        self.assertEqual(targets, [(0, 0), (0, 12), (0, 12)])
        self.assertEqual(o.exports, [])
        self.assertIn("no local label 'y' after", errors(".l y: br .f =y\n"))
        self.assertIn("use .b =z", errors(".l z: br =z\n"))

    def test_label_minus_const(self):
        o = asm_ok("a: mova r2a, =a - 2\n.data\n.addr =a + 0x10, 7\n")
        self.assertEqual([(r.type, r.target, r.index) for r in o.relocations], [("IMM16", 0, -2), ("ABS16", 0, 16)])
        self.assertEqual(bytes(o.sections[1].data), bytes([0x10, 0x00, 0x07, 0x00]))
        img = link_objs([o]).image
        self.assertEqual(img[2:4], bytes([0xFF, 0xFE]))
        self.assertEqual(img[4:6], bytes([0x10, 0x00]))

    def test_label_only_in_imm16(self):
        self.assertIn("8 bit immediate", errors("a: mov r0, =a\n"))
        self.assertIn("use .addr", errors("a: mov r0, #0\n.data\n.byte =a\n"))

    def test_register_widths(self):
        self.assertIn("16 bit register pair", errors("mova r1, r2a\n"))
        self.assertIn("8 bit register", errors("mov r1a, r2\n"))
        self.assertIn("must be a register", errors("str #1, r2a\n"))
        self.assertIn("r15a", " ".join(asm_text("br r15a\n").warnings))

    def test_ranges(self):
        self.assertIn("does not fit in 8 bits", errors("mov r0, #256\n"))
        self.assertIn("does not fit in 16 bits", errors("mova r0a, #65536\n"))
        asm_ok("mov r0, #-128\nmov r0, #255\n")
        self.assertIn("takes 2 operands", errors("mov r0\n"))
        self.assertIn("unknown condition", errors("add.xx r0, r0, r0\n"))

    def test_case_insensitive_instructions(self):
        a = bytes(asm_ok("ADD.EQ R1, R2, #3\nBR R4A\n").sections[0].data)
        b = bytes(asm_ok("add.eq r1, r2, #3\nbr r4a\n").sections[0].data)
        self.assertEqual(a, b)

    def test_numbers(self):
        o = asm_ok(".data\n.byte 0b101, 0o17, 0d9, 0x1F, '\\n', -1\n.dword 0x1234\n.qword 1\n")
        self.assertEqual(bytes(o.sections[0].data).hex(), "050f091f0aff341201000000")


class Preprocessor(unittest.TestCase):
    def test_define_and_include(self):
        o = asm_ok("!INCLUDE regs.inc\nmov !cnt, !LIMIT\n",
                   extra={"regs.inc": "!DEFINE cnt r1\n!DEFINE LIMIT #0x10\n"})
        self.assertEqual(bytes(o.sections[0].data), bytes([0x00, 0x11, 0x00, 0x10]))

    def test_errors_carry_location(self):
        r = asm_text("mov r0, #0\nbogus r1\n", name="x.s")
        self.assertTrue(r.errors[0].endswith("x.s:2: unknown instruction 'bogus'"), r.errors)
        r = asm_text("!INCLUDE missing.inc\n", name="y.s")
        self.assertTrue(r.errors[0].endswith("y.s:1: cannot read 'missing.inc'") or "cannot read" in r.errors[0])


if __name__ == "__main__":
    unittest.main()
