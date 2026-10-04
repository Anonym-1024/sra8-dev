"""Linker and linker scripts (spec Section 5; Section 10, item 5)."""

import unittest

from util import asm_ok, link_errors, link_objs

from sra8.ld import script
from sra8.ld.output import ihex_text, map_text, mem_text
from sra8.ld.script import ScriptError

BOOTISH = """
    memory boot start 0x0000 size 0x100
    memory ram  start 0x1000 size 0x100
    place boot
        code vector
        code *
        data *
    end
    place ram
        symbol __bss_start
        bss *
        symbol __bss_end
    end
    symbol top = last ram
    symbol base = start ram
    symbol magic = 0x1234
"""


class Placement(unittest.TestCase):
    def test_two_objects_and_cross_references(self):
        a = asm_ok(".import g\n.export f\nf: brl r12a, =g\n")
        b = asm_ok(".import f\n.export g\ng: br =f\n")
        res = link_objs([a, b])
        self.assertEqual(res.image, bytes([0x07, 0x5C, 0x00, 0x04, 0x07, 0x30, 0x00, 0x00]))

    def test_named_sections_star_and_order(self):
        a = asm_ok(".code\nmov r0, #1\n.code vector\nmov r0, #2\n.data\n.byte 0xAA\n")
        b = asm_ok(".code\nmov r0, #3\n.data rodata\n.byte 0xBB\n.data\n.byte 0xCC\n")
        res = link_objs([a, b], BOOTISH)
        img = res.image
        self.assertEqual(img[0:4], bytes([0x00, 0x10, 0x00, 0x02]))      # vector first
        self.assertEqual(img[4:8], bytes([0x00, 0x10, 0x00, 0x01]))      # then unnamed code, a before b
        self.assertEqual(img[8:12], bytes([0x00, 0x10, 0x00, 0x03]))
        self.assertEqual(img[12:15], bytes([0xAA, 0xCC, 0xBB]))          # unnamed data, then named

    def test_script_symbols(self):
        o = asm_ok(".import top, base, magic, __bss_start, __bss_end\n"
                   "mova r0a, =top\nmova r0a, =base\nmova r0a, =magic\nmova r0a, =__bss_start\nmova r0a, =__bss_end\n"
                   ".bss\n.res 7\n")
        img = link_objs([o], BOOTISH).image
        vals = [int.from_bytes(img[i + 2:i + 4], "big") for i in range(0, 20, 4)]
        self.assertEqual(vals, [0x10FF, 0x1000, 0x1234, 0x1000, 0x1007])

    def test_code_is_4_aligned_and_align(self):
        a = asm_ok(".data\n.byte 1\n")
        b = asm_ok("x: mov r0, #0\n")
        res = link_objs([a, b], """
            memory m start 0 size 0x100
            place m
                data *
                code *
                align 16
                symbol after
            end""")
        self.assertEqual(res.base[(1, 0)], 4)
        self.assertEqual(res.image[:8], bytes([1, 0, 0, 0, 0x00, 0x10, 0x00, 0x00]))
        self.assertEqual({s.name: s.addr for s in res.symbols}["after"], 16)

    def test_bss_not_in_image(self):
        o = asm_ok("mov r0, #0\n.bss\n.res 100\n")
        res = link_objs([o])
        self.assertEqual(len(res.image), 4)

    def test_bss_between_loaded_sections_is_a_gap(self):
        o = asm_ok("mov r0, #0\n.bss\n.res 4\n.data\n.byte 9\n")
        res = link_objs([o], """
            memory m start 0 size 0x100
            place m
                code *
                bss *
                data *
            end""")
        self.assertEqual(res.image, bytes([0x00, 0x10, 0x00, 0x00, 0, 0, 0, 0, 9]))


class Errors(unittest.TestCase):
    def test_duplicate_export(self):
        a = asm_ok(".export f\nf: br =f\n")
        self.assertIn("exported by both", " ".join(link_errors([a, a])))

    def test_unresolved(self):
        a = asm_ok(".import nowhere\nbr =nowhere\n")
        self.assertIn("undefined symbol 'nowhere'", " ".join(link_errors([a])))

    def test_unresolved_but_not_exported(self):
        a = asm_ok(".import f\nbr =f\n")
        b = asm_ok("f: br =f\n")
        self.assertIn("undefined symbol 'f'", " ".join(link_errors([a, b])))

    def test_unplaced(self):
        a = asm_ok(".code special\nmov r0, #0\n")
        e = " ".join(link_errors([a], "memory m start 0 size 16\nplace m\n code\nend\n"))
        self.assertIn("code:special", e)
        self.assertIn("not placed", e)

    def test_overflow(self):
        a = asm_ok(".data\n.res 20\n")
        e = " ".join(link_errors([a], "memory m start 0 size 16\nplace m\n data *\nend\n"))
        self.assertIn("does not fit into region 'm'", e)

    def test_script_symbol_clash(self):
        a = asm_ok(".export top\ntop: br =top\n")
        self.assertIn("also exported", " ".join(link_errors([a], BOOTISH)))


class ScriptSyntax(unittest.TestCase):
    def bad(self, text, msg):
        with self.assertRaises(ScriptError) as cm:
            script.parse(text, "s.ld")
        self.assertIn(msg, str(cm.exception))

    def test_errors(self):
        self.bad("memory a start 0 size 0x10\nmemory b start 8 size 0x10\n", "overlaps")
        self.bad("memory a start 0xFFF0 size 0x20\n", "within 0x0000")
        self.bad("place nowhere\nend\n", "unknown region")
        self.bad("memory a start 0 size 16\nplace a\n code\n", "not closed")
        self.bad("code *\n", "only allowed inside")
        self.bad("memory a start 0 size 16\nplace a\n foo\nend\n", "not allowed inside")
        self.bad("symbol x = 1 + 2\n", "expected  symbol")
        self.bad("memory a start 0 size zz\n", "bad number")
        self.bad("memory a start 0 size 16\nplace a\nend\nplace a\nend\n", "already has a place")

    def test_comments_and_numbers(self):
        s = script.parse("; c\nmemory a start 0b10 size 0x10 ; c\nsymbol s = 42\n")
        self.assertEqual((s.regions["a"].start, s.regions["a"].size, s.symbols[0].value), (2, 16, 42))


class Outputs(unittest.TestCase):
    def test_mem(self):
        res = link_objs([asm_ok("mov r0, #0x5A\n")])
        text = mem_text(res, 8)
        self.assertEqual(text, "@0000\n00 10 00 5A\n00 00 00 00\n")

    def test_mem_needs_start_0(self):
        res = link_objs([asm_ok("mov r0, #0\n")], "memory m start 0x100 size 16\nplace m\n code\nend\n")
        with self.assertRaises(Exception):
            mem_text(res, 4096)

    def test_ihex(self):
        res = link_objs([asm_ok(".data\n.byte 1, 2, 3\n")], "memory m start 0x100 size 16\nplace m\n data\nend\n")
        self.assertEqual(ihex_text(res), ":03010000010203F6\n:00000001FF\n")

    def test_map_mentions_everything(self):
        res = link_objs([asm_ok(".export main\nmain: br =main\n")])
        m = map_text(res, "flat.ld")
        for word in ("Memory regions", "Sections", "Symbols", "main", "exported"):
            self.assertIn(word, m)


if __name__ == "__main__":
    unittest.main()
