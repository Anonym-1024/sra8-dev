# SRA-8 development kit

Assembler, linker and disassembler for the SRA-8 CPU of the
`sra-8-fpga` project, with start-up code, a runtime library, and VS Code
syntax highlighting. The design is described in
[SRA8_DEVKIT_SPEC.md](SRA8_DEVKIT_SPEC.md).

```
  main.s ──sra8-as──▶ main.o ─┐
  lib/crt0.s, lib/*.s ─▶ *.o ─┼──sra8-ld -T script.ld──▶ program.mem / .bin / .hex, .map, .lst
```

The tools are written in Python 3 (3.10 or newer; 3.9 also works) with
the standard library only. A C23 port with identical behaviour is in
[c/](c/README.md). The C-like language Y comes later.

## Running the tools from anywhere

```bash
make install
```

This puts symbolic links to `bin/sra8-as`, `bin/sra8-ld` and
`bin/sra8-objdump` into `~/.local/bin`. The links point into this
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

Build a program that uses `crt0` and the runtime:

```bash
make examples
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

Further documentation: [docs/isa.md](docs/isa.md) is the instruction set,
generated from `sra8/isa.py`. [docs/obj.md](docs/obj.md) is the object
format. [docs/abi.md](docs/abi.md) covers the calling convention, `crt0`
and the runtime routines.

## Layout

| Path | Content |
|---|---|
| `sra8/` | the Python package: `isa.py` (the only place opcode numbers live), `obj.py`, `objdump.py`, `asm/`, `ld/` |
| `bin/` | launchers: `sra8-as`, `sra8-ld`, `sra8-objdump` |
| `lib/` | `crt0.s`, `isr_default.s`, and the runtime: multiply, divide, shifts, block copy, UART |
| `ldscripts/` | `boot.ld` (default, with `crt0`) and `flat.ld` (legacy layout) |
| `examples/` | the six sample programs of the FPGA project, ported by removing `.org`, and `rt/hello.s` using the runtime |
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
round trips, the runtime link, and the VS Code grammar. The RTL checks are
skipped when `../sra-8-fpga/sra-8-fpga` is missing; set `SRA8_RTL` to
point elsewhere. `make c` builds and tests the C port.

`make docs` and `make vscode` regenerate `docs/isa.md` and the assembly
grammar after a change to the instruction set. `make golden` regenerates
`tests/golden` with the legacy assembler.

## VS Code

The extension in `vscode/sra8-lang` highlights SRA-8 assembly (`.s`,
`.inc`) and linker scripts (`.ld`). Install it by linking the folder into
the extensions directory once, then reload VS Code:

```bash
ln -s "$PWD/vscode/sra8-lang" ~/.vscode/extensions/sra8-lang
```

Other extensions may also claim `.s`. In that case pick "SRA-8 Assembly"
with the language selector in the status bar, or add a
`"files.associations"` entry to the workspace settings.
