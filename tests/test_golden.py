"""The ported sample programs give the legacy assembler's bytes (spec 10, items 2-3)."""

import os
import unittest

from util import EXAMPLES, GOLDEN, LDSCRIPTS, asm_file

from sra8.ld import layout, script
from sra8.ld.output import mem_text

SAMPLES = ("echo", "loader", "terminal", "user_echo", "example", "demo")


def build(name):
    path = os.path.join(EXAMPLES, "asm", name + ".s")
    r = asm_file(path)
    if r.errors:
        raise AssertionError(r.errors)
    flat = script.load(os.path.join(LDSCRIPTS, "flat.ld"))
    return layout.link(flat, [path], [r.obj])


class Golden(unittest.TestCase):
    def read(self, name, mode="rb"):
        with open(os.path.join(GOLDEN, name), mode) as f:
            return f.read()

    def test_bin(self):
        for name in SAMPLES:
            with self.subTest(name):
                self.assertEqual(build(name).image, self.read(name + ".bin"))

    def test_mem(self):
        for name in SAMPLES:
            with self.subTest(name):
                self.assertEqual(mem_text(build(name), 4096), self.read(name + ".mem", "r"))

    def test_f_l_vectors(self):
        """Every line of the legacy listing f.l: address and bytes."""
        img = build("loader").image
        n = 0
        for line in self.read("loader_f.l", "r").split("\n"):
            parts = line.split("  ", 2)
            if len(parts) < 2 or len(parts[0]) != 4:
                continue
            addr = int(parts[0], 16)
            data = bytes.fromhex(parts[1].split("   ")[0].strip()) if len(parts) > 2 else b""
            if data:
                self.assertEqual(img[addr:addr + len(data)], data, line)
                n += 1
        self.assertGreater(n, 50)


if __name__ == "__main__":
    unittest.main()
