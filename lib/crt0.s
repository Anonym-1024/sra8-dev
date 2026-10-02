; crt0.s -- start-up code (spec Section 8).
;
; Link it first:  sra8-ld -T ldscripts/boot.ld crt0.o main.o ...
; The section 'code vector' is placed at address 0 by boot.ld, and the
; unnamed code section of this file follows it directly.
;
; Address 0 is both the reset entry and the interrupt entry (INTPC is 0
; whenever the CPU enters interrupt mode).  In normal mode the intpcw is
; harmless; in interrupt mode it jumps to the handler.

        .import __isr, main, __stack_top, __bss_start, __bss_end

        .code vector
        .export _start
_start: intpcw =__isr             ; interrupt entry; harmless at reset

        .code
        mova  r14a, =__stack_top  ; stack pointer: next free byte, grows down
        ; zero the bss: RAM above the boot image is undefined after reset
        mova  r4a, =__bss_start
        mova  r6a, =__bss_end
        mov   r0, #0
.l zero:
        cmp   r4, r6              ; 16 bit compare r4a - r6a
        subcd r5, r7
        br.geu .f =done           ; r4a >= r6a
        str   r0, r4a
        adds  r4, r4, #1
        addc  r5, r5, #0
        br    .b =zero
.l done:
        brl   r12a, =main
.l spin:
        br    .b =spin            ; main returned: stop here
