; uart.s -- UART helpers (ABI of spec 7.7).
;
;   void  uart_putc(uint8 c)       send c, then wait until it is on the wire
;   uint8 uart_getc(void)          wait for a received byte and return it
;   bool  uart_avail(void)         1 if a received byte is waiting
;   void  uart_puts(char[]* s)     send the zero-terminated string s
;
; Receiving polls the IRQ bit of INTR, so it works only while the IRQ is
; masked (PSR bit 5 clear, the state after reset).  With the IRQ enabled
; the byte goes to the interrupt handler instead.  There is no receive
; buffer: a byte that arrives before the previous one was read replaces it.
;
; The port has no busy flag.  A byte takes 10 bit times on the wire,
; 10 x 104 = 1040 clocks at UART_DIV = 104 (115200 baud); a ptw before that
; is lost.  After every ptw these routines wait UART_TX_PASSES passes of
; a two-instruction loop, 116 clocks each.  Change the constant together
; with UART_DIV in CPU.v: passes >= 10 x UART_DIV / 116, plus one.

!DEFINE UART_TX_PASSES  #10
!DEFINE INTR_IRQ        #0x10           ; IRQ bit of INTR, as read by intrr

        .export uart_putc, uart_getc, uart_avail, uart_puts

        .code
uart_putc:
        adds  r4, r14, #1
        addc  r5, r15, #0
        ldr   r0, r4a
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
        br    r12a

uart_avail:
        intrr r1
        mov   r0, #0
        andd  r1, !INTR_IRQ
        mov.ne r0, #1
        br    r12a

uart_puts:
        adds  r4, r14, #1
        addc  r5, r15, #0
        ldr   r2, r4a             ; r2a = s
        adds  r4, r4, #1
        addc  r5, r5, #0
        ldr   r3, r4a
.l next:
        ldr   r0, r2a
        cmp   r0, #0
        br.eq r12a
        ptw   r0
        mov   r1, !UART_TX_PASSES
.l wait_puts:
        subs  r1, r1, #1
        br.ne .b =wait_puts
        adds  r2, r2, #1
        addc  r3, r3, #0
        br    .b =next
