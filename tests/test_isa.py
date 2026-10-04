"""Instruction table checks (spec Section 10, item 1) and encoding vectors (item 2)."""

import os
import re
import unittest

from util import RTL, asm_ok, link_objs

from sra8 import isa


class IsaTable(unittest.TestCase):
    def test_every_opcode_defined_once_or_undefined(self):
        for op in range(128):
            self.assertTrue((op in isa.OPCODES) != (op in isa.UNDEFINED_OPCODES), op)
        self.assertEqual(isa.UNDEFINED_OPCODES,
                         (7, 11, 15, 19, 23, 27, 119, 121, 123) + tuple(range(124, 128)))

    def test_register_forms_are_even(self):
        for ins in isa.INSTRUCTIONS.values():
            self.assertEqual(ins.opcode % 2, 0, ins.mnemonic)

    def test_no_removed_mnemonics(self):
        for m in ("movs", "mvn", "mvns"):
            self.assertNotIn(m, isa.INSTRUCTIONS)

    def test_decode_inverts_encode(self):
        for op, (ins, imm) in isa.OPCODES.items():
            regs = tuple(range(1, 1 + len(ins.fmt.regs) + (0 if imm or not ins.fmt.src else 1)))
            word = isa.encode(9, op, regs + (0,) * (3 - len(regs)), 0x34 if imm else 0)
            d = isa.decode(word)
            self.assertIsNotNone(d, ins.mnemonic)
            self.assertEqual((d.ins, d.imm_form, d.cond), (ins, imm, 9))

    def test_decode_rejects_noncanonical(self):
        self.assertIsNone(isa.decode(bytes([0x08, 0x00, 0x00, 0x00])))   # bit 27
        self.assertIsNone(isa.decode(bytes([0x00, 0x70, 0x00, 0x00])))   # opcode 7
        self.assertIsNone(isa.decode(bytes([0x00, 0x01, 0x23, 0x00])))   # mov r1, r2 with arg3 set


@unittest.skipUnless(os.path.isdir(RTL), "RTL folder not found")
class AgainstRtl(unittest.TestCase):
    def test_opcode_enum_of_control_rom_gen(self):
        with open(os.path.join(RTL, "control_unit_gen", "control_rom_gen.c")) as f:
            src = f.read()
        enum = dict((m.group(1), int(m.group(2))) for m in re.finditer(r"OPC_(\w+)\s*=\s*(\d+)", src))
        self.assertTrue(enum)
        for name, value in enum.items():
            imm = name.endswith("_I")
            mnemonic = (name[:-2] if imm else name).lower()
            self.assertIn(mnemonic, isa.INSTRUCTIONS, name)
            ins = isa.INSTRUCTIONS[mnemonic]
            self.assertEqual(ins.opcode | (1 if imm else 0), value, name)
        for ins in isa.INSTRUCTIONS.values():
            self.assertIn(ins.mnemonic.upper(), enum)
            self.assertEqual(ins.fmt.has_imm, ins.mnemonic.upper() + "_I" in enum, ins.mnemonic)

    def test_step_counts_and_undefined_microcode(self):
        with open(os.path.join(RTL, "control_rom.mem")) as f:
            rom = [int(l, 16) for l in f if l.strip()]
        # 16 steps per opcode; control word: MUX 3 (ucr = 5) in bits 5:3
        self.assertEqual(len(rom), 128 * 16)
        for op in range(128):
            words = rom[op * 16:op * 16 + 16]
            if op in isa.UNDEFINED_OPCODES:
                self.assertFalse(any(words), op)
                continue
            ucr = [i for i, w in enumerate(words) if (w >> 3) & 7 == 5]
            self.assertTrue(ucr, op)
            self.assertEqual(ucr[0] + 1, isa.OPCODES[op][0].steps, op)


class EncodingVectors(unittest.TestCase):
    """The table of spec 2.7, assembled in context so labels resolve."""

    VECTORS = [
        ("cmp r0, #0xA5", "05 F0 00 A5"),
        ("add.ne r9, r9, #1", "92 B9 90 01"),
        ("ors r1, r6, r7", "04 01 67 00"),
        ("str r0, r2a", "01 E0 20 00"),
        ("ldr r0, r2a", "01 C0 20 00"),
        ("br r10a", "07 2A 00 00"),
        ("svc", "07 A0 00 00"),
        ("ptr r0", "07 60 00 00"),
        ("ptw r0", "07 80 00 00"),
        ("intrr r1", "01 A1 00 00"),
        ("psrw #0x40", "01 10 00 40"),
        ("sub.su r7, r7, #1", "43 37 70 01"),
        ("andd r1, #0x10", "06 31 00 10"),
        ("MOV R1, R2", "00 01 20 00"),
        ("mova r2a, #-1", "00 32 FF FF"),
        ("mov r3, #'a'", "00 13 00 61"),
        # base + offset, post-increment, lea: rD | rBa | off12 in bits 11:0 or rOa in arg3
        ("ldo r0, r14a, #5", "02 10 E0 05"),
        ("ldo r1, r2a, r4a", "02 01 24 00"),
        ("sto r5, r8a, #2047", "02 35 87 FF"),
        ("sto r5, r8a, #-2048", "02 35 88 00"),
        ("ldi r3, r2a, #1", "02 53 20 01"),
        ("ldi r3, r2a, r6a", "02 43 26 00"),
        ("sti r0, r14a, #-1", "02 70 EF FF"),
        ("sti r0, r14a, r6a", "02 60 E6 00"),
        ("lea r14a, r14a, #-20", "02 9E EF EC"),
        ("lea r4a, r2a, r6a", "02 84 26 00"),
        ("ldo.eq r0, r2a, #0", "12 10 20 00"),
    ]

    def test_offset_errors(self):
        from util import asm_text
        for text, msg in (("ldo r0, r2a, #2048", "does not fit in 12 signed bits"),
                          ("sto r0, r2a, #-2049", "does not fit in 12 signed bits"),
                          ("ldo r0, r2, #1", "must be a 16 bit register pair"),
                          ("ldo r0, r2a, r4", "must be a 16 bit register pair"),
                          ("lea r4, r2a, #1", "must be a 16 bit register pair"),
                          ("ldo r0, r2a, =somewhere", "signed 12 bit offset")):
            r = asm_text(".import somewhere\n.code\n" + text + "\n")
            self.assertTrue(any(msg in e for e in r.errors), (text, r.errors))

    def test_disassembly_of_offsets(self):
        for text in ("ldo r0, r14a, #5", "sti r0, r14a, #-1", "lea r14a, r14a, #-20", "ldi r3, r2a, r6a"):
            o = asm_ok(".code\n" + text + "\n")
            d = isa.decode(bytes(o.sections[0].data))
            self.assertEqual(" ".join(d.text().split()), text)

    def test_vectors(self):
        for text, want in self.VECTORS:
            o = asm_ok(".code\n" + text + "\n")
            self.assertEqual(bytes(o.sections[0].data).hex(" ").upper(), want, text)

    def test_label_vectors(self):
        src = ".code\n" + "\n".join("        .res 4" for _ in range(0x29)) + "\n" + \
              "enter_program: br =enter_program\n"
        o = asm_ok(src + "intpcw =enter_program\nbrl r12a, =enter_program\n")
        img = link_objs([o]).image
        self.assertEqual(img[0xA4:0xA8].hex(" ").upper(), "07 30 00 A4")
        self.assertEqual(img[0xA8:0xAC].hex(" ").upper(), "00 D0 00 A4")
        self.assertEqual(img[0xAC:0xB0].hex(" ").upper(), "07 5C 00 A4")


if __name__ == "__main__":
    unittest.main()
