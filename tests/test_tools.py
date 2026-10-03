"""Disassembler round trips, runtime, examples, command lines and the VS Code
grammar (spec Section 10, items 6 and the runtime part of step 2)."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from util import EXAMPLES, LDSCRIPTS, LIB, ROOT, asm_file, asm_text

from sra8 import isa
from sra8.ld import layout, script
from sra8.objdump import ObjectPrinter, disassemble_image
from test_golden import SAMPLES, build

FLAT = os.path.join(LDSCRIPTS, "flat.ld")
BOOT = os.path.join(LDSCRIPTS, "boot.ld")


def relink(source_text):
    r = asm_text(source_text)
    if r.errors:
        raise AssertionError(r.errors[:3])
    return layout.link(script.load(FLAT), ["x.o"], [r.obj]).image


class RoundTrip(unittest.TestCase):
    def test_images(self):
        for name in SAMPLES:
            with self.subTest(name):
                img = build(name).image
                self.assertEqual(relink(disassemble_image(0, img)), img)

    def test_objects(self):
        for name in SAMPLES:
            with self.subTest(name):
                r = asm_file(os.path.join(EXAMPLES, "asm", name + ".s"))
                self.assertEqual(relink(ObjectPrinter(r.obj).text()), build(name).image)

    def test_addr_inside_code(self):
        src = ".export a\na: mov r0, #0\n.addr =a, =a\nbr =a\n"
        r = asm_text(src)
        self.assertEqual(r.errors, [])
        img = layout.link(script.load(FLAT), ["x.o"], [r.obj]).image
        self.assertEqual(relink(ObjectPrinter(r.obj).text()), img)

    def test_garbage_bytes(self):
        img = bytes(range(256)) + b"\x01\x02\x03"
        self.assertEqual(relink(disassemble_image(0, img)), img)


class Runtime(unittest.TestCase):
    def objects(self, *extra):
        paths = [os.path.join(LIB, "crt0.s")] + list(extra) + \
                [os.path.join(LIB, f) for f in ("isr_default.s", "uart.s", "rt_mul.s", "rt_div.s",
                                                 "rt_shift.s", "rt_mem.s")]
        objs = []
        for p in paths:
            r = asm_file(p)
            self.assertEqual(r.errors, [], p)
            self.assertEqual(r.warnings, [], p)
            objs.append(r.obj)
        return paths, objs

    def test_runtime_links_with_boot_ld(self):
        paths, objs = self.objects(os.path.join(EXAMPLES, "rt", "hello.s"))
        res = layout.link(script.load(BOOT), paths, objs)
        syms = {s.name: s.addr for s in res.symbols}
        self.assertEqual(syms["_start"], 0)
        self.assertEqual(res.image[0:2], bytes([0x00, 0xD0]))        # intpcw at address 0
        self.assertEqual(syms["__stack_top"], 0xFFFF)
        for name in ("__mul16", "__mul32", "__divu16", "__mods32", "__shl16", "__sar32", "__copy", "__zero",
                     "uart_putc", "uart_getc", "uart_avail", "uart_puts", "__isr", "main"):
            self.assertIn(name, syms)
        self.assertLessEqual(len(res.image), 4096)

    def test_main_is_required(self):
        paths, objs = self.objects()
        with self.assertRaises(layout.LinkError) as cm:
            layout.link(script.load(BOOT), paths, objs)
        self.assertIn("undefined symbol 'main'", " ".join(cm.exception.errors))


class CommandLines(unittest.TestCase):
    def run_tool(self, tool, *args):
        return subprocess.run([sys.executable, os.path.join(ROOT, "bin", tool)] + list(args),
                              capture_output=True, text=True)

    def test_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            o = os.path.join(d, "t.o")
            p = self.run_tool("sra8-as", os.path.join(EXAMPLES, "asm", "terminal.s"), "-o", o, "-l", os.path.join(d, "t.lst"))
            self.assertEqual(p.returncode, 0, p.stderr)
            mem = os.path.join(d, "t.mem")
            p = self.run_tool("sra8-ld", "-T", FLAT, "--format", "mem", "-o", mem, "-M", os.path.join(d, "t.map"), o)
            self.assertEqual(p.returncode, 0, p.stderr)
            with open(mem) as f, open(os.path.join(ROOT, "tests", "golden", "terminal.mem")) as g:
                self.assertEqual(f.read(), g.read())
            p = self.run_tool("sra8-objdump", "-d", "-t", "-r", o)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("exports", p.stdout)        # non-exported labels are not in objects:
            self.assertIn("=L0_01E0", p.stdout)       # targets get generated names

    def test_errors_exit_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "bad.s")
            with open(src, "w") as f:
                f.write("mov r0, #0\nbr =nowhere\n")
            p = self.run_tool("sra8-as", src, "-o", os.path.join(d, "bad.o"))
            self.assertEqual(p.returncode, 1)
            self.assertIn("bad.s:2: error: undefined name 'nowhere'", p.stderr)

    def test_werror(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "w.s")
            with open(src, "w") as f:
                f.write(".import unused\nmov r0, #0\n")
            self.assertEqual(self.run_tool("sra8-as", src, "-o", os.path.join(d, "w.o")).returncode, 0)
            self.assertEqual(self.run_tool("sra8-as", src, "-Werror", "-o", os.path.join(d, "w.o")).returncode, 1)


class Zed(unittest.TestCase):
    """The Zed grammars match their generator; with the tree-sitter CLI, the
    queries compile and the example files parse without errors."""

    ZED = os.path.join(ROOT, "zed")
    LANGS = {"sra8asm": ("sra8-asm", [os.path.join(EXAMPLES, "asm", "terminal.s"), os.path.join(LIB, "rt_div.s")]),
             "sra8ld": ("sra8-ld", [os.path.join(LDSCRIPTS, "boot.ld"), os.path.join(LDSCRIPTS, "flat.ld")]),
             "ylang": ("y", [])}

    def test_grammar_json_current(self):
        sys.path.insert(0, self.ZED)
        import gen_grammars
        for name, g in gen_grammars.GRAMMARS.items():
            with open(os.path.join(self.ZED, "tree-sitter", name, "src", "grammar.json")) as f:
                on_disk = json.load(f)
            generated = json.loads(json.dumps(g))
            generated["rules"] = {k: gen_grammars.r(v) for k, v in generated["rules"].items()}
            self.assertEqual(on_disk["rules"], generated["rules"], "%s: run make zed" % name)
            self.assertTrue(os.path.exists(os.path.join(self.ZED, "tree-sitter", name, "src", "parser.c")))

    @unittest.skipUnless(shutil.which("tree-sitter"), "tree-sitter CLI not installed")
    def test_queries_and_parsing(self):
        for name, (lang, samples) in self.LANGS.items():
            grammar = os.path.join(self.ZED, "tree-sitter", name)
            queries = os.path.join(self.ZED, "languages", lang, "highlights.scm")
            for sample in samples:
                p = subprocess.run(["tree-sitter", "parse", "-p", grammar, "-q", sample],
                                   capture_output=True, text=True)
                self.assertNotIn("ERROR", p.stdout, sample)
            # the query must compile against the grammar; any file of the language will do
            target = samples[0] if samples else os.path.join(EXAMPLES, "asm", "echo.y")
            p = subprocess.run(["tree-sitter", "query", "-p", grammar, queries, target],
                               capture_output=True, text=True)
            self.assertNotIn("Query error", p.stdout + p.stderr, name)
            self.assertIn("capture:", p.stdout, name)


class VsCode(unittest.TestCase):
    """The grammar must know every instruction and condition of isa.py."""

    def grammar(self, name):
        with open(os.path.join(ROOT, "vscode", "sra8-lang", "syntaxes", name)) as f:
            return f.read()

    def test_asm_grammar_lists_all_mnemonics(self):
        text = self.grammar("sra8-asm.tmLanguage.json")
        json.loads(text)
        m = re.search(r'"name": "keyword.mnemonic.sra8asm",\s*"match": "([^"]+)"', text)
        self.assertIsNotNone(m)
        listed = set(re.findall(r"[a-z]+", m.group(1).split("(?:\\\\.")[0]))
        self.assertTrue(set(isa.INSTRUCTIONS) <= listed, set(isa.INSTRUCTIONS) - listed)
        for cond in isa.CONDITIONS:
            self.assertIn(cond, m.group(1))

    def test_ylang_extension(self):
        """The Y grammar is current and knows every word of its generator's lists."""
        sys.path.insert(0, os.path.join(ROOT, "vscode", "ylang"))
        import gen_grammar
        with open(os.path.join(ROOT, "vscode", "ylang", "syntaxes", "ylang.tmLanguage.json")) as f:
            text = f.read()
        self.assertEqual(json.loads(text), json.loads(json.dumps(gen_grammar.grammar())), "run make vscode")
        for ws in gen_grammar.WORD_LISTS.values():
            for w in ws:
                self.assertIn(w, text)
        with open(os.path.join(ROOT, "vscode", "ylang", "package.json")) as f:
            pkg = json.load(f)
        self.assertEqual(pkg["contributes"]["languages"][0]["extensions"], [".y", ".yh"])
        rules = pkg["contributes"]["configurationDefaults"]["editor.tokenColorCustomizations"]["textMateRules"]
        self.assertIn({"scope": gen_grammar.LOGIC_SCOPE, "settings": {"fontStyle": "bold"}}, rules)
        for rule in gen_grammar.grammar()["repository"].values():
            for q in rule.get("patterns", [rule]):
                re.compile(q.get("match") or q["begin"])

    def test_package_json(self):
        with open(os.path.join(ROOT, "vscode", "sra8-lang", "package.json")) as f:
            pkg = json.load(f)
        ids = {l["id"] for l in pkg["contributes"]["languages"]}
        self.assertEqual(ids, {"sra8-asm", "sra8-ld"})
        for g in pkg["contributes"]["grammars"]:
            json.loads(self.grammar(os.path.basename(g["path"])))


if __name__ == "__main__":
    unittest.main()
