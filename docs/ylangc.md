# ylangc — the Y compiler, version 0.4

```
ylangc [-o out.s] [-I dir]... [-D NAME[=text]]... file.y
```

One `.y` file in, one assembly file out (default name: the source name with
`.s`). The compiler never runs the assembler or the linker. Errors are
printed as `file:line: error: text`; compilation stops at the first one.

Version 0.4 is still simple, but tries to keep programs small (see "What
it costs" below). It implements the language of [y.md](y.md) except:

- `@reg` is rejected;
- there is no hardware access (ports, interrupts, inline assembly): call
  assembly routines written to the ABI below instead, as
  [examples/y/uart.s](../examples/y/uart.s) does.

The output is commented: every function starts with its signature, the
frame layout is listed above each frame, every source line appears as a
comment before its code, and every instruction says what it does.

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
`__stack_top`, `__bss_start` and `__bss_end`, as `boot.ld` does.

## ABI 0.4

Changes from 0.3: the header before a function is only there when a call
through a pointer may need it; a leaf function does not save `r12a`; the
start-up code zeroes `.bss`; arguments are written as soon as they are
computed; the helpers of `*`, `/`, `%` are assembly routines.

A function that is not `@recursive` has a **static frame**; each call of a
`@recursive` function gets a **stack frame**. Both are reached with the
offset addressing modes of the CPU (`ldo`, `sto`, `lea`; see
[isa.md](isa.md)).

### Static frames

Every function `f` without `@recursive` has a static frame: a block of
memory in `.bss` labelled `f.frame`. It holds, in this order:

| Offset | Content |
|---|---|
| 0 | the result, if `f` returns one |
| next | the parameters, in order, each little-endian, structs and arrays whole |
| next | the saved return address (`r12a`, 2 bytes) |
| next | the locals, then spill slots and scratch space of the compiler |

Every byte of a frame is reached with **one instruction**:
`ldr r0, =f.frame+5`. The layout of each frame is listed as a comment above
it in the output.

`f` and `f.frame` are exported together, unless `f` is `@internal`.

### Stack frames

A `@recursive` function `g` has no `g.frame`. Each call builds its frame on
the stack, so calls of `g` can be active at the same time. The stack grows
down and `SP` (`r14a`) points at the next free byte. The start-up code sets
it to `__stack_top` (0xFFFF with `boot.ld`). After the prologue of `g`:

| Address | Content | Written by |
|---|---|---|
| `SP + 1` … | the locals, spill slots and scratch space (`L` bytes) | `g` |
| `SP + 1 + L` | the saved return address (2 bytes) | `g` |
| `SP + 1 + F` | the result, if `g` returns one (`R` bytes) | the caller (room only) |
| next | the parameters, in order | the caller |

`F = L + 2` is the size of the stack frame. Every byte is reached with
`ldo`/`sto rX, r14a, #offset`. When the offset is beyond the 12-bit range
(±2047, a frame over 2 KiB), `mova r10a, #offset` and
`lea r10a, r14a, r10a` come first, then `ldo`/`sto rX, r10a, #0`.

```
g:      lea     r14a, r14a, #-F           ; prologue: the frame
        sto     r12, r14a, #L+1           ; save the return address
        sto     r13, r14a, #L+2
        …
        ldo     r12, r14a, #L+1           ; return: reload the return address
        ldo     r13, r14a, #L+2
        lea     r14a, r14a, #F            ; free the frame
        br      r12a
```

A pointer to a local of `g` points into the stack frame of the call that
took it. It stays valid while that call runs, also in deeper calls of `g`.

### The header

Right before the code of a function is a 4-byte **header**: the address of
its static frame (`.addr =f.frame`), or 0 for a `@recursive` function
(`.addr 0`), then the frame size (`.dword size`). A call through a function
pointer reads the first word at `f - 4` (`ldo …, r10a, #-4` and `#-3`) to
choose the convention.

Only such calls read it, so it is there for every exported function and
for every function whose address is taken (`@ptr(f)`), and left out for an
`@internal` function whose address is never taken. An assembly routine
needs it if Y code may call it through a pointer.

### Registers

| Register | Use |
|---|---|
| `r0` … `r9` | values while an expression is computed |
| `r10a` (`r11:r10`) | address register for accesses through pointers and far offsets |
| `r12a` (`r13:r12`) | link register: `brl r12a, …` writes the return address |
| `r14a` (`r15:r14`) | stack pointer `SP`: stack frames, and the arguments of `@recursive` calls |

**Every register may be changed by a call**, except `SP`, which a function
returns unchanged. Nothing is passed in registers.

### A call

If `g` is **not `@recursive`**, the caller:

1. writes the arguments into `g.frame`, after the result, each as soon as
   it is computed. Arguments before the last one that calls a function
   (or uses `*`, `/`, `%`, which call helpers) wait in registers or spill
   slots until that one is done, since its call could be `g` itself;
2. calls: `brl r12a, =g`;
3. reads the result from `g.frame`.

If `g` is **`@recursive`**, with `A` the size of the result and the
arguments together, the caller:

1. `lea r14a, r14a, #-A`: room for the result and the arguments;
2. writes each argument at `SP + 1 + R` … as soon as it is computed (calls
   made meanwhile use the stack below, so they cannot disturb them);
3. calls: `brl r12a, =g`;
4. reads the result at `SP + 1`;
5. `lea r14a, r14a, #A`.

A call through a pointer loads the header word at `f - 4` and branches to
one of the two sequences: a non-zero word is the static frame to write the
arguments into, through `r10a`; 0 means the stack. The call itself is
`brl r12a, r10a`.

The callee saves `r12a` in its frame on entry, and on `return` writes the
result into its frame (into the caller's area, for a stack frame), reloads
`r12a` and returns with `br r12a`. A **leaf function**, one that calls
nothing, leaves the return address in `r12a` and does neither (its frame
keeps the 2 bytes for it, unused).

### `@recursive` is not checked

A static frame holds one call of a function at a time. A function that can
be called while it runs, directly or through other functions or function
pointers, must be `@recursive`, and a `decl` must carry `@recursive` when
the function has it. **The compiler does not check this.** A function
without `@recursive` that is re-entered overwrites its own parameters,
locals and return address, and typically loops or returns to the wrong
place.

### Start-up and names

- The `@main` function must be `fn()` without a result. Its file gets the
  start-up code in `.code vector`:

  ```
  _start: mova    r14a, =__stack_top
          mova    r2a, =__bss_start       ; zero .bss: __bss_start ...
          mova    r4a, =__bss_end         ; ... up to __bss_end
          mov     r0, #0
  .l zero:
          cmp     r2, r4
          subcd   r3, r5
          br.geu  .f =zeroed
          sti     r0, r2a, #1
          br      .b =zero
  .l zeroed:
          brl     r12a, =main_function
  .l spin:
          br      .b =spin
  ```

  The loop zeroes the `.bss` of every linked file, so a global whose
  initial value is all zero bytes goes to `.bss` instead of taking room in
  the image. A program with its own start-up code must zero `.bss` too.
  `undefined` still means unspecified.
- A Y name is the assembly label: `impl f` is `f:`, `var g` is `g:`.
  Names that are only declared with `decl` and used are imported, with
  `f.frame` for called functions that are not `@recursive`.
- Code goes to `.code`, or to `.code name` with `@section(name)`. Global
  variables with a value go to `.data`; all-zero, `undefined` ones and the
  frames to `.bss`. String literals go to `.data` as `str.N`. Labels inside a
  function are `function.N`; Y names cannot contain a dot, so they never
  collide.
- `*`, `/` and `%` call helpers, unless the right operand is a constant
  the compiler can do without one (below). The helpers are assembly
  routines ([sra8/ylang/prelude.py](../sra8/ylang/prelude.py)) added to
  every file that uses them, internal, with a static frame and no header,
  so no run-time library is needed. With `n` the operand size in bytes:

  | Routine | Frame | Used by |
  |---|---|---|
  | `__mul8`, `__mul16`, `__mul32` | +0 `a * b`, +n `a`, +2n `b` | `*` (signed and unsigned) |
  | `__divmodu8` … `__divmodu32` | +0 `a / b`, +n `a`, +2n `b`, +3n `a % b` | unsigned `/` and `%` |
  | `__divmods8` … `__divmods32` | the same, +4n and +4n+1: signs | signed `/` and `%` |

  `/` and `%` call the same routine and read the quotient or the
  remainder. Signed division rounds toward 0; the remainder has the sign
  of `a`. The 32-bit routines use `r12` as their loop counter and save the
  return address in their frame.

### Assembly routines

A routine written in assembly follows the same rules: a frame label
`name.frame` holding its result and parameters, the 4-byte header before
its entry, both exported. A leaf routine needs no room for `r12a`:

```
        .bss
uart_putc.frame:        .res 1          ; +0 c
        .code
        .addr   =uart_putc.frame        ; header: the frame ...
        .dword  1                       ; ... and its size
uart_putc:
        ldr     r0, =uart_putc.frame    ; r0 = c
        ptw     r0
        …
        br      r12a
```

## Code generation

- **Every variable lives in memory**: globals at their label, locals and
  parameters in the frame. A statement loads what it needs and stores its
  result; nothing stays in a register from one statement to the next.
- **While an expression is computed**, intermediate values stay in
  `r0` … `r9`. Both operands of an operation are in registers before it
  runs, so multi-byte arithmetic is one `adds`/`addcs`/`addc` chain. When
  the registers run out, the oldest value goes to a spill slot in the frame.
- **At every call and every branch inside an expression** (`and`, `or`,
  `@bool`, copies), all values are written to their spill slots, so every
  label is reached with nothing in registers.
- Conditions become branches: multi-byte `eq`/`ne` compare by `eor`/`or`;
  `lt`/`ge` use `cmp` + `subcd` and `su`/`geu` (unsigned) or `ss`/`ges`
  (signed); `gt`/`le` swap the operands.
- Shifts by a constant are unrolled up to 24 instructions, otherwise a loop
  shifts one bit per pass. Struct and array copies are a byte loop of
  `ldi`/`sti` (4 instructions per byte, 6 when more than 255 bytes).
- **Constant operands of `*`, `/`, `%`**: `x * c` is shifts and adds when
  that takes at most 16 instructions (`x * 10` with 16-bit `x`: 10),
  `x / 2^k` and `x % 2^k` (unsigned) are shifts and an `and`. A constant on
  the left of `+`, `*`, `&`, `|`, `^`, `eq`, `ne` is moved to the right,
  where it is an immediate.
- **Through a pointer**, `r10a` is set once, then each byte is reached
  with `ldo`/`sto rX, r10a, #offset`; struct fields add their offset there.
  A pointer variable of a static frame is loaded straight into `r10a`.
- **Indexing** `p[i]` and `a[i]` keeps the scaled index in a register pair:
  one byte is `ldo`/`sto rX, r10a, rIa`, a larger element
  `lea r10a, r10a, rIa`, then `#0`, `#1`, ….
- A narrowing `@cast` of a variable, element, field or call result loads
  only the bytes it keeps. Constants are set again with `mov` instead of
  being spilled and reloaded.
- **Branches** are cleaned up within each function: no branch to the next
  instruction, no code after an unconditional branch until the next label
  that is used, a branch to a `br` goes to its target, and
  `br.cc =A / br =B / A:` becomes `br.!cc =B`. `if (x) { break; }` is one
  conditional branch.

### What it costs

| Program | 0.1 | 0.2 | 0.3 | 0.4 |
|---|---|---|---|---|
| 72 random int16 expressions | 318 784 cycles | 173 328 cycles | 173 328 cycles | 97 260 cycles |
| the feature test program, code and data | 19 072 bytes | 12 676 bytes | 10 724 bytes | 6 535 bytes |
| `hello.y` with `uart.s` | 746 bytes | 426 bytes | 426 bytes | 350 bytes |
| a UART terminal (echo, sum; 3 files) | | | 4 023 bytes | 2 183 bytes |

Version 0.2 brought static frames: one instruction per frame access instead
of three. In 0.2, a call of a `@recursive` function copied the whole frame
to the stack and back, about 10 instructions per byte; since 0.3 the call
costs two `lea`, the argument stores and the result loads.

In 0.4 the largest savings in the terminal program came from the helpers
(three Y-compiled routines of 808 bytes became one assembly routine of
100 bytes, `len / 2` a shift), from indexing with a register pair, from
writing arguments straight into the callee's frame and from the branch
clean-up. The `.bss` loop costs 32 bytes once. Most of the remaining code
moves values between the frame and the registers: nothing stays in a
register from one statement to the next, which a register allocator would
change.
