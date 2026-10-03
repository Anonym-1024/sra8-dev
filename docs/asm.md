# sra8-as — the assembler

```
sra8-as [-o out.o] [-l out.lst] [-Werror] file.s
```

One source file in, one relocatable object out (default name: the source
name with `.o`). The assembler never produces an image; placement is the
linker's job. Errors and warnings are printed as `file:line: error: text`.
Exit status 1 on any error, or on any warning with `-Werror`.

The instruction set itself is in [isa.md](isa.md).

## Lexical rules

- `;` starts a comment. It is the only comment syntax: `//` and `/*` are errors.
- Mnemonics, registers and condition suffixes are case-insensitive. Labels and directives are case-sensitive.
- Numbers: `123`, `0d123`, `0x7B`, `0o173`, `0b1111011`, `'a'`, optionally with a leading `-` or `+`. Character escapes: `\n \t \r \0 \\ \' \"`. A number beyond 64 bits is reported as a bad number.
- Registers: `r0` … `r15`. Pairs `r0a` … `r15a` mean r(N+1):rN, low byte in rN. `r15a` draws a warning because its high byte wraps to `r0`.
- Names: `[A-Za-z_][A-Za-z0-9_.]*`. Names starting with `__` are reserved for the toolchain.

## Statements

```
[label:]* [.l local:]* [mnemonic[.cond] operands | .directive args]   [; comment]
```

Only the real instructions of [isa.md](isa.md) exist. There are no
pseudo-instructions; the usual idioms are:

| Idea | Write |
|---|---|
| no-op | `mov.nvr r0, r0` |
| call / return | `brl r12a, =f` / `br r12a` |
| stop | `.l spin: br .b =spin` |
| 16-bit add | `adds lo, lo, x` then `addc hi, hi, y` |
| 16-bit subtract | `subs lo, lo, x` then `subc hi, hi, y` |

## Operands

| Operand | Meaning |
|---|---|
| `rN`, `rNa` | register, register pair |
| `#number` | immediate, 8 or 16 bits by instruction format (−128 … 255, −32768 … 65535) |
| `=label` | address of a label, wherever a 16-bit immediate is allowed |
| `=label + n`, `=label - n` | address plus or minus a constant |
| `.b =label`, `.f =label` | nearest local label before / after this line; `± n` works here too |

No other expressions exist: no arithmetic between constants, no
`label − label`, no current-address operator, no `lo()` / `hi()`.

## Labels, import and export

| Directive | Meaning |
|---|---|
| `name:` | label in the current section, visible in this file |
| `.l name:` | local label; may be defined many times; never in the object |
| `.export a, b` | make labels of this file visible to other objects |
| `.import a, b` | names defined in another object |

There is no implicit import: a reference to a name that is neither defined
nor imported is an error. Importing a name that is also defined is an
error, and so is exporting an undefined or imported name. An unused import
is a warning. There are no weak symbols and no constant symbols; use
`!DEFINE` for named constants.

## Sections

| Directive | Allowed content |
|---|---|
| `.code [name]` | instructions and data directives |
| `.data [name]` | data directives |
| `.bss [name]` | `.res` only; no bytes in the object or image |

A section is identified by its type and its optional name. Before the
first section directive the unnamed `.code` section is current. Reopening
a section continues it.

Inside a code section every instruction must start at an offset that is a
multiple of 4; the linker places every code section at a multiple of 4.
Together this keeps instructions inside one 256-byte page, which the fetch
microcode requires.

`.org` and `.align` do not exist. Placement is done by the linker script.

## Data directives

| Directive | Bytes | Values |
|---|---|---|
| `.byte v, …` / `.word v, …` | 1 each | numbers (`.word` is 8 bits on this CPU) |
| `.dword v, …` | 2 each, little-endian | numbers |
| `.qword v, …` | 4 each, little-endian | numbers |
| `.addr v, …` | 2 each, little-endian | numbers or `=label [± n]` |
| `.ascii "s"` / `.asciz "s"` | length / length + 1 | Latin-1 text |
| `.res n` | n | nothing in `.bss`, zero bytes elsewhere |

In directive arguments the `#` before a number is optional.

## Preprocessor

| Line | Meaning |
|---|---|
| `!INCLUDE path` | paste the file, path relative to the including file |
| `!DEFINE name text` | define an alias |
| `!name` | replaced by the text, outside quotes, recursively |

## Listing

`-l` writes the statements with section-relative offsets, then the
sections, labels, imports and relocations. Bytes that a relocation fills
show the index or addend until linking. The listing is the only place
that shows labels which are not exported: the object file does not keep
them. Final addresses of the exported labels are in the linker's map.

## Porting legacy programs

Programs of the legacy `asm/sra8asm.py` assemble unchanged after deleting
the `.org #0x0000` line. Linked with `ldscripts/flat.ld` they give
byte-identical `.bin` and `.mem` files; the test suite checks
this for the six sample programs in `examples/asm`.
