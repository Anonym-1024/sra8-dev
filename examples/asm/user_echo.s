; Echo program for loader.s.  It runs in privilege level 1 behind the page
; table of the loader, so it is linked at virtual address 0 although it sits
; at physical address 0x0400.  The message is read with ldr, which shows
; that data addresses are translated as well as the fetches.
;
; Assemble with:  asm/sra8asm user_echo.s -f bin -o user_echo.bin
; or make arduino_loader/program.h from it:  python3 arduino_loader/make_program.py user_echo.s
;
; The IRQ is masked, the program polls INTR for a received byte instead.
; An interrupt handler would not fit here: interrupt mode is not translated,
; its handler has to be given as a physical address.

!DEFINE INTR_IRQ #0x10          ; IRQ bit of INTR, as read by intrr
!DEFINE TX_WAIT  #96            ; putc delay = 256 - 96 passes, about 1.6 ms (one byte is 1.04 ms)

.code
        mova  r2a, =msg_hello
.l print:
        ldr   r0, r2a
        cmp   r0, #0
        br.eq .f =echo
        ptw   r0
        mov   r1, !TX_WAIT
.l wait:
        adds  r1, r1, #1
        br.su .b =wait          ; su = carry clear
        adds  r2, r2, #1
        addc  r3, r3, #0
        br    .b =print

.l echo:
        intrr r1
        andd  r1, !INTR_IRQ
        br.eq .b =echo
        ptr   r0                ; read the byte, this drops the port's IRQ
        intrw #0                ; clear the latched IRQ
        ptw   r0                ; send it back
        br    .b =echo

.data
msg_hello:      .asciz "hello from pl 1\r\n"
