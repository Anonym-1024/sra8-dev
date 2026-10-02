# C23 port of the SRA-8 tools

`sra8-as`, `sra8-ld` and `sra8-objdump` in C23 with the standard library
only, plus `isagen`, which prints the instruction table as Markdown or as
the VS Code grammar and checks it against the RTL. They behave exactly
like the Python tools in the parent folder: same objects, images, maps,
assembler listings, disassembly and messages. The one difference: numbers beyond
64 bits are reported as a bad number.

```bash
make
```

```bash
make test
```

The programs go to `c/bin/`. The tests (`tests/run.sh`, POSIX shell) use
the shared examples, runtime, linker scripts and goldens of the parent
folder, and check that `docs/isa.md` and the VS Code grammar, which the
Python tools generate, agree with the C instruction table.

Tested with Apple clang 17 and gcc 15 (`make CC=gcc-15`), both without
warnings. `make SANITIZE=address,undefined clean test` runs the tests
under the sanitizers. `.clangd` makes clangd treat the sources as C23.
