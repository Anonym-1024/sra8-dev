# ylangc — the Y compiler, version 0.1

```
ylangc [-o out.s] [-I dir]... [-D NAME[=text]]... file.y
```

One `.y` file in, one assembly file out (default name: the source name with
`.s`). The compiler never runs the assembler or the linker. Errors are
printed as `file:line: error: text`; compilation stops at the first one.

Version 0.1 is deliberately simple and brute force: correct first, small
and fast later. It implements the language of [y.md](y.md) except:

- `@reg` is rejected ("not supported by ylangc 0.1");
- there is no hardware access (ports, interrupts, inline assembly): call
  assembly routines written to the ABI below instead, as
  [examples/y/uart.s](../examples/y/uart.s) does.

## Building a program

```bash
ylangc examples/y/hello.y -o build/hello.s
```

```bash
sra8-as build/hello.s -o build/hello.o
```

```bash
sra8-as examples/y/uart.s -o build/uart.o
```

```bash
sra8-ld -T ldscripts/boot.ld --format mem -o program.mem build/hello.o build/uart.o
```

`make examples` does the same for every example. The file with the
`@main` function contains the start-up code, so it needs a linker script
that places the section `code vector` at address 0 and defines
`__stack_top`, as `boot.ld` does.

## ABI 0.1

### Registers

| Register | Use |
|---|---|
| `r0` … `r9` | values while an expression is computed |
| `r10a` (`r11:r10`) | address register: every access to the stack frame or through a pointer goes through it |
| `r12a` (`r13:r12`) | link register: `brl r12a, …` writes the return address |
| `r14a` (`r15:r14`) | stack pointer `SP` |

**Every register may be changed by a call**, except `SP`, which a function
returns unchanged. Nothing is passed in registers.

### The stack

The stack grows down. `SP` points at the **next free byte**, so the bytes
in use start at `SP + 1`. The start-up code sets `SP` to `__stack_top`
(0xFFFF with `boot.ld`).

### A call

The caller:

1. lowers `SP` by `R + A`: `R` bytes for the result (0 without one) and `A`
   for the arguments;
2. writes the arguments, in order, after the result: the first argument
   at `SP + 1 + R`, the next one after it, each little-endian, structs
   and arrays copied whole;
3. calls: `brl r12a, =f`, or for a function pointer, the address in
   `r10a` and `brl r12a, r10a`;
4. reads the result from `SP + 1` … `SP + R`;
5. raises `SP` by `R + A` again.

The callee, with `F` the size of its frame:

```
        higher addresses
        │ last argument        │
        │ …                    │
        │ first argument       │  SP + F + R + 1
        │ result (R bytes)     │  SP + F + 1         the caller's area
        ├──────────────────────┤
        │ saved r12a (2 bytes) │  SP + F − 1, SP + F
        │ locals, spill slots  │  SP + 1 …
        └──────────────────────┘  ← SP (next free byte)
        lower addresses
```

- prologue: `SP ← SP − F`, store `r12a` at the top of the frame;
- `return x;` writes `x` into the result area;
- epilogue: load `r12a`, `SP ← SP + F`, `br r12a`.

A leaf routine written in assembly may skip the frame: its first argument
(or its result) is then at `SP + 1`, as in `uart.s`:

```
uart_putc:                      ; fn(c: char)
        adds  r10, r14, #1      ; r10a = SP + 1: the argument c
        addc  r11, r15, #0
        ldr   r0, r10a
        ptw   r0
        …
        br    r12a
```

### Names, sections, start-up

- A Y name is the assembly label: `impl f` is `f:`, `var g` is `g:`.
  Non-`internal` functions and variables are exported; names that are
  only declared with `decl` and used are imported.
- Code goes to `.code`, or to `.code name` with `@section(name)`. Global
  variables with a value go to `.data`, `undefined` ones to `.bss`. String
  literals go to `.data` as `str.N`.
- Labels inside a function are `function.N`. Y names cannot contain a dot,
  so they never collide.
- The `@main` function must be `fn()` without a result. Its file gets the
  start-up code in `.code vector`:

  ```
  _start: mova    r14a, =__stack_top
          brl     r12a, =main_function
  .l spin:
          br      .b =spin
  ```

  Nothing zeroes `.bss`: `undefined` means unspecified.
- `*`, `/` and `%` call helpers (`__mul16`, `__divs32`, …). They are
  written in Y ([sra8/ylang/prelude.py](../sra8/ylang/prelude.py)) and
  compiled into every file that uses them, as internal functions, so no
  run-time library is needed.

## Code generation

- **Every variable lives in memory**, always: globals at their label,
  locals and parameters in the frame. A statement loads what it needs and
  stores its result; nothing stays in a register from one statement to
  the next.
- **While an expression is computed**, intermediate values stay in
  `r0` … `r9`. Both operands of an operation are in registers before it
  runs, so multi-byte arithmetic is one `adds`/`addcs`/`addc` chain.
  When the registers run out, the oldest value is written to a spill slot
  in the frame and loaded again when needed.
- **At every call and every branch inside an expression** (`and`, `or`,
  `@bool`, copies), all values are written to their spill slots, so every
  label is reached with nothing in registers.
- Conditions become branches. Multi-byte `eq`/`ne` compare by
  `eor`/`or`; `lt`/`ge` use `cmp` + `subcd` and the conditions
  `su`/`geu` (unsigned) or `ss`/`ges` (signed); `gt`/`le` swap the
  operands.
- Shifts by a constant are unrolled up to 24 instructions, otherwise a loop
  shifts one bit per pass. Struct and array copies are a byte loop.

### What it costs

A frame access is three instructions: `adds r10, r14, #k`,
`addc r11, r15, #0`, then `ldr`/`str`. Measured on the test programs, these
address computations are **47 % of the code and of the executed cycles**.
An `ldr`/`str` with a register pair plus an 8-bit offset (for example
`ldr rD, r14a, #k`) would make every frame access one instruction, roughly
halve code size and double speed, and would leave the flags alone.

Code size matters: the boot ROM holds 4 KiB. `hello.y` with `uart.s` is
746 bytes.
