; hello.s -- an assembly program that uses crt0 and the runtime, following
; the ABI of spec 7.7.  It prints a greeting and then echoes every byte.
;
; Build (see examples/Makefile):
;   sra8-as lib/crt0.s ... ; sra8-ld -T ldscripts/boot.ld --format mem crt0.o hello.o uart.o isr_default.o

        .import uart_puts, uart_getc, uart_putc
        .export main

        .code
main:                             ; never returns, so the link register need not be saved
        mova  r4a, =greeting      ; push the argument: high byte first, so that it
        str   r5, r14a            ; is little-endian in memory
        subs  r14, r14, #1
        subc  r15, r15, #0
        str   r4, r14a
        subs  r14, r14, #1
        subc  r15, r15, #0
        brl   r12a, =uart_puts
        adds  r14, r14, #2        ; the caller removes its arguments
        addc  r15, r15, #0
.l echo:
        brl   r12a, =uart_getc    ; -> r0
        str   r0, r14a            ; push it
        subs  r14, r14, #1
        subc  r15, r15, #0
        brl   r12a, =uart_putc
        adds  r14, r14, #1
        addc  r15, r15, #0
        br    .b =echo

        .data rodata
greeting:
        .asciz "hello from crt0 and the runtime\r\n"
