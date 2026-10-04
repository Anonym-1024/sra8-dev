# SRA-8 development kit

Assembler, linker, disassembler and a first Y compiler for the SRA-8 CPU
of the `sra-8-fpga` project, with syntax highlighting for VS Code and Zed.
The design is described in [SRA8_DEVKIT_SPEC.md](SRA8_DEVKIT_SPEC.md), the
Y language in [docs/y.md](docs/y.md) and its compiler in
[docs/ylangc.md](docs/ylangc.md).

```
  main.y ──ylangc──▶ main.s ──sra8-as──▶ main.o ─┐
                     uart.s ──sra8-as──▶ uart.o ─┼──sra8-ld -T script.ld──▶ program.mem / .bin / .hex, .map
```

The tools are written in Python 3 (3.10 or newer; 3.9 also works) with
the standard library only. A C23 port with identical behaviour is in
[c/](c/README.md).

## Running the tools from anywhere

```bash
make install
```

This puts symbolic links to `bin/sra8-as`, `bin/sra8-ld`,
`bin/sra8-objdump` and `bin/ylangc` into `~/.local/bin`. The links point into this
checkout, so an edit or a `git pull` takes effect immediately, and the
linker keeps finding its default script in `ldscripts/`. Nothing is
copied, and `make uninstall` removes the links.

`~/.local/bin` has to be on your PATH. If it is not, `make install` says
so; add this line to `~/.zshrc` and open a new terminal:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Alternatively install into a folder that is already on PATH, such as
`/usr/local/bin`:

```bash
make install PREFIX=/usr/local
```

Without installing, run the tools as `bin/sra8-as` from this folder.

## Quick start

Rebuild the FPGA's `program.mem` from the terminal sample:

```bash
sra8-as examples/asm/terminal.s -o terminal.o
```

```bash
sra8-ld -T ldscripts/flat.ld --format mem -o program.mem terminal.o
```

Build all sample programs into `examples/build/`, including
`hello.mem`, a Y program that greets and echoes over the UART:

```bash
make examples
```

Compile a Y file to assembly:

```bash
ylangc examples/y/hello.y -o hello.s
```

Look inside an object or an image:

```bash
sra8-objdump -d -t terminal.o
```

## Tools

| Tool | Does | Reference |
|---|---|---|
| `sra8-as` | `.s` to relocatable `.o` | [docs/asm.md](docs/asm.md) |
| `sra8-ld` | objects plus linker script to `.bin`, `.mem` or Intel HEX, with a map | [docs/ld.md](docs/ld.md) |
| `sra8-objdump` | disassembles objects and images into source that assembles again; dumps sections, exports, imports and relocations | `sra8-objdump --help` |
| `ylangc` | Y to assembly (version 0.1: simple and unoptimised) | [docs/ylangc.md](docs/ylangc.md) |

Further documentation: [docs/isa.md](docs/isa.md) is the instruction set,
generated from `sra8/isa.py`. [docs/obj.md](docs/obj.md) is the object
format. [docs/y.md](docs/y.md) defines the Y language; its calling
convention and compiler are still to come.

## Layout

| Path | Content |
|---|---|
| `sra8/` | the Python package: `isa.py` (the only place opcode numbers live), `obj.py`, `objdump.py`, `asm/`, `ld/`, `ylang/` (the Y compiler) |
| `bin/` | launchers: `sra8-as`, `sra8-ld`, `sra8-objdump`, `ylangc` |
| `ldscripts/` | `boot.ld` (default: boot ROM and RAM) and `flat.ld` (legacy layout) |
| `examples/` | the six sample programs of the FPGA project, ported by removing `.org`; `y/`: a Y program with UART routines in assembly, and `tour.y`, every construct of Y |
| `tests/` | the `unittest` suite; `golden/` holds the legacy assembler's output |
| `docs/` | reference documentation |
| `vscode/sra8-lang/` | VS Code extension for `.s` and `.ld` files |
| `c/` | the C23 port, its own Makefile and tests |

## Tests

```bash
make test
```

The tests check the instruction table against the RTL's microcode
sources, encoding vectors, byte-identical output against the legacy
assembler for six programs, assembler and linker diagnostics, disassembly
round trips, the boot script, and the editor grammars. The RTL checks are
skipped when `../sra-8-fpga/sra-8-fpga` is missing; set `SRA8_RTL` to
point elsewhere. `make c` builds and tests the C port.

`make docs` and `make vscode` regenerate `docs/isa.md` and the assembly
grammar after a change to the instruction set. `make golden` regenerates
`tests/golden` with the legacy assembler.

## VS Code

Two extensions in `vscode/` provide syntax highlighting:

| Extension | Files | Language id |
|---|---|---|
| `vscode/sra8-lang` | SRA-8 assembly (`.s`, `.inc`) and linker scripts (`.ld`) | `sra8-asm`, `sra8-ld` |
| `vscode/ylang` | the Y language (`.y`, `.yh`) of [docs/y.md](docs/y.md) | `ylang` |

Install each by linking its folder into the extensions directory once,
then reload VS Code:

```bash
ln -s "$PWD/vscode/sra8-lang" ~/.vscode/extensions/sra8-lang
```

```bash
ln -s "$PWD/vscode/ylang" ~/.vscode/extensions/ylang
```

Other extensions may also claim `.s` (assemblers) or `.y` (yacc and
bison). In that case pick the language with the selector in the status
bar, or map the extension in the settings:

```json
"files.associations": {
    "*.s": "sra8-asm",
    "*.y": "ylang"
}
```

`make vscode` regenerates both grammars: the assembly one from
`sra8/isa.py`, the Y one from the word lists at the top of
`vscode/ylang/gen_grammar.py`.

## Zed

The extension in `zed/` gives Zed syntax highlighting for SRA-8 assembly
(`.s`, `.inc`), linker scripts (`.ld`) and Y (`.y`, `.yh`). The Y word
operators (`and`, `or`, `not`, `eq` …, `shl`, `ror` …) are bold, in one
colour, in every theme.

Zed highlights with Tree-sitter parsers, which it compiles itself from a
committed revision of this repository. To install:

1. Commit the `zed/` folder.
2. Write `zed/extension.toml`, which points Zed at that commit:

   ```bash
   make zed-extension
   ```

3. In Zed, open the command palette, run "zed: install dev extension" and
   pick the `zed` folder.

After changing a grammar, run `make zed` (it needs the Tree-sitter CLI:
`cargo install tree-sitter-cli`), commit, run `make zed-extension` again,
and rebuild the extension from Zed's extensions page. Changes to the
`.scm` query files in `zed/languages/` only need the rebuild.

| Path | Content |
|---|---|
| `zed/gen_grammars.py` | the three grammars, written as Tree-sitter `grammar.json` |
| `zed/tree-sitter/*/src/` | the generated parsers, committed so Zed needs no generator |
| `zed/languages/*/` | per language: `config.toml`, `highlights.scm` and brackets / indents |
