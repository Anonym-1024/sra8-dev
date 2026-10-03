# Object file format

A JSON text file with the extension `.o`, written by `sra8-as` and read by
`sra8-ld` and `sra8-objdump`. One list element per line, so objects diff
well. Version 2.

```json
{
  "format": "sra8-obj",
  "version": 2,
  "source": "boot.s",
  "sections": [
    {"section": "code:vector", "size": 4, "data": "00D00000"},
    {"section": "code", "size": 52, "data": "003E0000…"},
    {"section": "bss", "size": 81}
  ],
  "exports": [
    {"name": "_start", "section": "code:vector", "offset": 0}
  ],
  "relocations": [
    {"section": "code:vector", "offset": 0, "type": "IMM16", "import": "irq_handler", "addend": 0},
    {"section": "code", "offset": 24, "type": "IMM16", "from": "code", "index": 44}
  ]
}
```

It has four parts.

| Part | Content |
|---|---|
| header | `format`, `version` and `source`, the name of the source file |
| `sections` | every section, by its label: the type, then `:name` for a named one (`code`, `code:vector`, `data:rodata`, `bss`). `data` is uppercase hex, exactly `size` bytes; bss has none. |
| `exports` | the exported labels: name, section label, offset. Labels that are not exported are not in the object. |
| `relocations` | every place where an address must be written in |

## Relocations

Every label reference becomes a relocation, also inside one section,
because addresses exist only after linking. A relocation says:

- **where**: `section` and `offset` of the bytes to patch,
- **how**: `type`,
- **what**: either `from` a section of this object at `index`, or an
  `import`ed name plus an `addend`.

| Type | Produced by | Patches |
|---|---|---|
| `IMM16` | `=label` in an instruction | bytes `offset+2` (high) and `offset+3` (low) of the instruction |
| `ABS16` | `.addr =label` | bytes `offset` (low) and `offset+1` (high) |

A reference to a label of the same file, exported or not, local `.l` or
not, uses `from` and `index`: the label's offset plus the constant of
`=label ± n`. The index may lie outside the section. The linker writes
the section's final address plus the index.

A reference to an imported name uses `import` and `addend`. The linker
looks the name up among the exports of all objects and the symbols of the
linker script, and writes its address plus the addend.

Values wrap at 16 bits. Before linking, the patched field holds the index
or the addend. The imported names of an object are exactly the names in
its `import` relocations.
