# ABI, start-up code and runtime

This is the calling convention of spec Section 7.7. Assembly that calls
the runtime must follow it, and so will the planned Y compiler.

## Registers

| Register | Role | Saved by |
|---|---|---|
| `r0` … `r3` | result, little-endian: 8 bit in `r0`, 16 bit in `r0a`, 32 bit in `r0` … `r3`; scratch otherwise | caller |
| `r4` … `r9` | scratch | caller |
| `r10a` | frame pointer FP | callee |
| `r12a` | link register LR: `brl r12a, =f` calls, `br r12a` returns | caller; a function that calls others saves it first |
| `r14a` | stack pointer SP | — |

## Stack

The stack grows down. SP points at the next free byte, so a push is a
store followed by a decrement, and the first byte above SP is the last one
pushed. `crt0` starts SP at `__stack_top` (0xFFFF with `boot.ld`). Every
adjustment changes the flags.

```
; push r4                         ; pop r4
        str   r4, r14a            ;         adds  r14, r14, #1
        subs  r14, r14, #1        ;         addc  r15, r15, #0
        subc  r15, r15, #0        ;         ldr   r4, r14a
```

## Calls

- The caller pushes the arguments, **last argument first**. A multi-byte
  argument is pushed high byte first, so it is little-endian in memory.
  The first argument then starts at SP + 1 when the callee is entered.
- The caller calls with `brl r12a, =f` and removes the arguments
  afterwards by adding their size to SP.
- A callee that needs a frame pushes LR, then FP, and sets FP = SP. The
  saved FP is at FP + 1 and FP + 2, the saved LR at FP + 3 and FP + 4, and
  the first argument at FP + 5. Locals are below FP.
- Results up to 4 bytes return in `r0` … `r3`. Larger results are written
  through a hidden first argument, a pointer the caller provides.

`examples/rt/hello.s` is a complete example in assembly.

## Start-up: `lib/crt0.s`

1. Section `code vector` holds `intpcw =__isr` and is placed at address 0.
   Address 0 is both the reset and the interrupt entry.
2. SP = `__stack_top`.
3. The bytes from `__bss_start` to `__bss_end` are zeroed. RAM above the
   boot image is undefined after reset.
4. `brl r12a, =main`; if `main` returns, the CPU spins.

Link `crt0.o` first. Link `lib/isr_default.o` unless the program defines
its own `__isr`; it only executes `intrw #0`.

## Runtime routines

Every routine follows the convention above. The arithmetic and shift
routines were checked against Python arithmetic on edge cases and random
values in an instruction-level model of the CPU. Cycle counts are the
worst case seen there, at 12 MHz.

| File | Routine | Operation | Worst cycles |
|---|---|---|---|
| `rt_mul.s` | `uint16 __mul16(uint16 a, uint16 b)` | low 16 bits of a × b; also for 8-bit products | 9 140 |
| | `uint32 __mul32(uint32 a, uint32 b)` | low 32 bits of a × b | 30 636 |
| `rt_div.s` | `__divu16`, `__modu16` | unsigned 16-bit a / b, a % b | 13 284 |
| | `__divs16`, `__mods16` | signed, rounded toward zero; remainder has the sign of a | 14 208 |
| | `__divu32`, `__modu32`, `__divs32`, `__mods32` | the same with 32 bits | 43 948 |
| `rt_shift.s` | `__shl16`, `__shr16`, `__sar16(v, uint8 n)` | 16-bit shift by n, one pass per bit | 20 788 at n = 40 |
| | `__shl32`, `__shr32`, `__sar32(v, uint8 n)` | 32-bit | 21 360 at n = 40 |
| `rt_mem.s` | `void __copy(void* dst, void* src, uint16 n)` | copy n bytes upward | 664 per byte |
| | `void __zero(void* dst, uint16 n)` | clear n bytes | 476 per byte |
| `uart.s` | `void uart_putc(uint8 c)` | send, then wait one byte time | — |
| | `uint8 uart_getc(void)` | wait for a byte; polls INTR | — |
| | `bool uart_avail(void)` | a received byte is waiting | — |
| | `void uart_puts(char[]* s)` | send a zero-terminated string | — |

Division by zero is undefined: it returns quotient 0xFFFF… and remainder a.
`__mul32` and the 32-bit division save and restore `r10a` and `r12a`
themselves because they need 13 registers.

### UART timing

The port has no busy flag, and a byte written while the previous one is
still being sent is lost. At `UART_DIV = 104` (115200 baud at 12 MHz) a
byte takes 1040 clocks. `uart.s` waits `UART_TX_PASSES` = 10 passes of a
116-clock loop after every byte. If `UART_DIV` in `CPU.v` changes, set
`UART_TX_PASSES` ≥ 10 × UART_DIV / 116 + 1.

Receiving polls the IRQ bit of INTR and therefore works only while the IRQ
is masked, which is the state after reset.
