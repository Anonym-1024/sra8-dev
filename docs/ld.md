# sra8-ld — the linker

```
sra8-ld [-T script.ld] [-o out] [--format bin|mem|ihex] [--mem-size N]
        [-M out.map] objects...
```

All objects on the command line are linked, in that order. There are no
libraries: shared routines are ordinary objects on the command line.
Without `-T` the script `ldscripts/boot.ld` of this repository is used,
also when the linker is called through a link made by `make install`.

The link fails, naming the culprit, when an import is not provided by any
export or script symbol, a name is exported twice, a section is not placed
by the script, or a region overflows.

## Linker script

One statement per line, `;` starts a comment, numbers are decimal, `0x…`
or `0b…`. The complete language:

```
memory NAME start ADDR size BYTES

place REGION
    code [NAME | *]
    data [NAME | *]
    bss  [NAME | *]
    align N
    symbol NAME
end

symbol NAME = NUMBER | start REGION | last REGION
```

| Statement | Meaning |
|---|---|
| `memory` | an address range; ranges must not overlap and lie within 0 … 0xFFFF |
| `place R … end` | fill region R from its start, in item order; one block per region |
| `code` | the unnamed code section of all objects, in command-line order |
| `code NAME` | the code section with that name; nothing if no object has it |
| `code *` | every code section not placed yet: unnamed first, then named ones by first appearance |
| `align N` | advance to a multiple of N; the gap is zero-filled |
| `symbol NAME` inside `place` | NAME = the current address |
| `symbol NAME = …` | a number, the first (`start`) or last (`last`) address of a region |

`data` and `bss` work like `code`. Code sections are always placed at a
multiple of 4. A section is placed once; the first item that matches it
wins. Script symbols behave like exported labels: objects reach them with
`.import`.

## Built-in scripts

| Script | Use |
|---|---|
| `ldscripts/boot.ld` | a program in the 4 KiB boot ROM: section `code vector` at 0, code and data up to 0x0FFF, bss from 0x1000, `__stack_top` = 0xFFFF. Defines `__bss_start`, `__bss_end`, `__stack_top`. |
| `ldscripts/flat.ld` | the legacy assembler's layout: everything from 0, code then data then bss. Used by the sample programs. |

## Outputs

The image holds all code and data bytes, from the start of the lowest
region that contains any to the last such byte. Gaps are zero. Bss
contributes no bytes.

| `--format` | Default name | Content |
|---|---|---|
| `bin` | `a.bin` | the image as raw bytes |
| `mem` | `a.mem` | Verilog `$readmemh` file: `@0000`, then `--mem-size` bytes (default 4096), four per line. The legacy `program.mem` format; the image must start at 0. |
| `ihex` | `a.hex` | Intel HEX, 16-byte records |

`-M` writes a map: regions with used and free bytes, every placed section
with its object, and every exported label and script symbol with its
address. Labels that are not exported are not in the objects, so the map
cannot show them; the assembler listing has them with section offsets.

## Algorithm

1. Read the objects; collect exports.
2. Run the script: place sections, define script symbols, check regions.
3. Resolve every relocation: a section of the same object plus an index,
   or an imported name looked up among all exports and script symbols,
   plus an addend.
4. Patch: `IMM16` writes bytes 2 and 3 of an instruction (big-endian),
   `ABS16` two data bytes (little-endian). Values wrap at 16 bits.
5. Write the outputs.
