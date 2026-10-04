; uart.s -- UART routines for Y programs, written to ABI 0.1 (docs/ylangc.md).
;
;   uart_putc: fn(c: char)              c is at SP+1
;   uart_getc: fn() returns char        the result goes to SP+1
;
; Both are leaf routines: they keep no frame and return with br r12a.
; Receiving polls the IRQ bit of INTR, so it works while the IRQ is masked
; (the state after reset).  The port has no busy flag: a byte takes
; 10 x UART_DIV = 1040 clocks on the wire, so uart_putc waits
; UART_TX_PASSES passes of a two-instruction loop (116 clocks each).

!DEFINE UART_TX_PASSES  #10
!DEFINE INTR_IRQ        #0x10           ; IRQ bit of INTR, as read by intrr

        .export uart_putc, uart_getc

        .code
uart_putc:
        adds  r10, r14, #1
        addc  r11, r15, #0
        ldr   r0, r10a
        ptw   r0
        mov   r1, !UART_TX_PASSES
.l wait:
        subs  r1, r1, #1
        br.ne .b =wait
        br    r12a

uart_getc:
        intrr r1
        andd  r1, !INTR_IRQ
        br.eq =uart_getc
        ptr   r0                  ; read the byte; this drops the port's IRQ line
        intrw #0                  ; clear the latched IRQ
        adds  r10, r14, #1
        addc  r11, r15, #0
        str   r0, r10a
        br    r12a
