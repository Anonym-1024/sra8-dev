; uart.s -- UART routines for Y programs, written to ABI 0.3 (docs/ylangc.md).
;
;   uart_putc: fn(c: char)              the caller writes c to uart_putc.frame
;   uart_getc: fn() returns char        the result goes to uart_getc.frame
;
; Like every function that is not @recursive (ABI 0.3), each routine has a
; static frame (name.frame) and a 4-byte header before its entry: the
; address and the size of the frame.  Both are leaf routines, so their frames need no room
; for the return address.
;
; Receiving polls the IRQ bit of INTR, so it works while the IRQ is masked
; (the state after reset).  The port has no busy flag: a byte takes
; 10 x UART_DIV = 1040 clocks on the wire, so uart_putc waits
; UART_TX_PASSES passes of a two-instruction loop (116 clocks each).

!DEFINE UART_TX_PASSES  #10
!DEFINE INTR_IRQ        #0x10           ; IRQ bit of INTR, as read by intrr

        .export uart_putc, uart_putc.frame, uart_getc, uart_getc.frame

        .bss
uart_putc.frame:        .res 1          ; +0 c
uart_getc.frame:        .res 1          ; +0 result

        .code
        .addr   =uart_putc.frame        ; header: the frame ...
        .dword  1                       ; ... and its size
uart_putc:
        ldr     r0, =uart_putc.frame    ; r0 = c
        ptw     r0                      ; send it
        mov     r1, !UART_TX_PASSES     ; wait until it is on the wire
.l wait:
        subs    r1, r1, #1
        br.ne   .b =wait
        br      r12a                    ; back to the caller

        .addr   =uart_getc.frame        ; header: the frame ...
        .dword  1                       ; ... and its size
uart_getc:
        intrr   r1                      ; r1 = INTR
        andd    r1, !INTR_IRQ           ; has a byte arrived?
        br.eq   =uart_getc              ; not yet: ask again
        ptr     r0                      ; read the byte; this drops the port's IRQ line
        intrw   #0                      ; clear the latched IRQ
        str     r0, =uart_getc.frame    ; result = the byte
        br      r12a                    ; back to the caller
