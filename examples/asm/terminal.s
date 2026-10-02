; SRA-8 terminal: a line based command prompt on the UART port.
;
;       echo <text>             prints <text>
;       sum <n> <n> ...         prints the sum of the decimal numbers (16 bit, wraps at 65536)
;
; A line ends with CR or LF, backspace deletes the last character.
;
; The program runs on its own in privilege level 0:
;       asm/sra8asm terminal.s -o program.mem
; or in privilege level 1, uploaded to loader.s by arduino_loader:
;       python3 arduino_loader/make_program.py terminal.s
; It uses no fixed addresses and no interrupt handler, so that it does not
; matter where in physical memory it ends up.
;
; Receiving: the IRQ stays masked.  INTR latches the port's IRQ anyway, so
; getc polls it with intrr.  There is no receive buffer: the sender has to
; leave about 5 ms between characters, as arduino_loader does.
;
; Sending: the port has no busy flag, putc waits out one byte time instead.
;
; Registers
;       r0              character argument / result
;       r1              scratch of the leaf routines
;       r2a  (r2:r3)    text pointer
;       r4a  (r4:r5)    16 bit sum
;       r6a  (r6:r7)    second pointer, number being parsed
;       r8, r9          16 bit temporary; r8 is the length of the line while it is typed
;       r10a (r10:r11)  return address of the leaf routines (getc, putc, match)
;       r12a (r12:r13)  return address of puts and print_dec, which call putc

!DEFINE INTR_IRQ  #0x10         ; IRQ bit of INTR, as read by intrr
!DEFINE LINE_MAX  #80
!DEFINE TX_WAIT   #96           ; putc delay = 256 - 96 passes, about 1.6 ms (one byte is 1.04 ms)

.code
        mova  r2a, =msg_banner
        brl   r12a, =puts

prompt:
        mova  r2a, =msg_prompt
        brl   r12a, =puts
        mova  r2a, =line
        mov   r8, #0            ; number of characters typed

read_char:
        brl   r10a, =getc
        cmp   r0, #13           ; CR
        br.eq =line_end
        cmp   r0, #10           ; LF
        br.eq =line_end
        cmp   r0, #8            ; backspace
        br.eq =backspace
        cmp   r0, #127          ; delete
        br.eq =backspace
        cmp   r8, !LINE_MAX
        br.geu =read_char       ; line full, drop the character
        str   r0, r2a
        adds  r2, r2, #1
        addc  r3, r3, #0
        add   r8, r8, #1
        brl   r10a, =putc       ; echo it
        br    =read_char

backspace:
        cmp   r8, #0
        br.eq =read_char
        sub   r8, r8, #1
        subs  r2, r2, #1        ; r2a = r2a - 1, the borrow by hand
        sub.su r3, r3, #1
        mov   r0, #8            ; step back, overwrite with a space, step back
        brl   r10a, =putc
        mov   r0, #' '
        brl   r10a, =putc
        mov   r0, #8
        brl   r10a, =putc
        br    =read_char

line_end:
        cmp   r8, #0            ; empty line, also the LF of a CR LF pair
        br.eq =read_char
        mov   r0, #0
        str   r0, r2a           ; terminate the line
        mova  r2a, =msg_newline
        brl   r12a, =puts

        mova  r2a, =line
        mova  r6a, =kw_echo
        brl   r10a, =match
        cmp   r1, #1
        br.eq =cmd_echo

        mova  r2a, =line
        mova  r6a, =kw_sum
        brl   r10a, =match
        cmp   r1, #1
        br.eq =cmd_sum

        mova  r2a, =msg_unknown
        brl   r12a, =puts
        br    =prompt

; ---- echo <text> ----------------------------------------------------------

cmd_echo:
        ldr   r0, r2a           ; skip the space after the keyword
        cmp   r0, #' '
        br.ne .f =print
        adds  r2, r2, #1
        addc  r3, r3, #0
.l print:
        brl   r12a, =puts
        mova  r2a, =msg_newline
        brl   r12a, =puts
        br    =prompt

; ---- sum <n> <n> ... ------------------------------------------------------

cmd_sum:
        mov   r4, #0
        mov   r5, #0

.l next_number:
        ldr   r0, r2a
        cmp   r0, #0
        br.eq =sum_print
        cmp   r0, #' '
        br.ne .f =number
        adds  r2, r2, #1
        addc  r3, r3, #0
        br    .b =next_number

.l number:
        mov   r6, #0
        mov   r7, #0
.l digit:
        ldr   r0, r2a
        cmp   r0, #0
        br.eq .f =number_end
        cmp   r0, #' '
        br.eq .f =number_end
        cmp   r0, #'0'
        br.su =sum_bad
        cmp   r0, #':'          ; the character after '9'
        br.geu =sum_bad

        mov   r8, r6            ; r6a = r6a * 10, by adding it up ten times
        mov   r9, r7
        mov   r6, #0
        mov   r7, #0
        mov   r1, #10
.l times10:
        adds  r6, r6, r8
        addc  r7, r7, r9
        subs  r1, r1, #1
        br.ne .b =times10

        sub   r0, r0, #'0'      ; r6a = r6a + digit
        adds  r6, r6, r0
        addc  r7, r7, #0
        adds  r2, r2, #1
        addc  r3, r3, #0
        br    .b =digit

.l number_end:
        adds  r4, r4, r6
        addc  r5, r5, r7
        br    .b =next_number

sum_print:
        brl   r12a, =print_dec
        mova  r2a, =msg_newline
        brl   r12a, =puts
        br    =prompt

sum_bad:
        mova  r2a, =msg_bad_number
        brl   r12a, =puts
        br    =prompt

; ---- subroutines ----------------------------------------------------------

; getc: wait for a received byte -> r0.  Returns through r10a, uses r1.
getc:
        intrr r1
        andd  r1, !INTR_IRQ
        br.eq =getc
        ptr   r0                ; read the byte, this drops the port's IRQ
        intrw #0                ; clear the latched IRQ
        br    r10a

; putc: send r0.  Returns through r10a, uses r1.
putc:
        ptw   r0
        mov   r1, !TX_WAIT
.l wait:
        adds  r1, r1, #8
        br.su .b =wait          ; su = carry clear
        br    r10a

; puts: send the zero terminated string at r2a.  Returns through r12a.
puts:
        ldr   r0, r2a
        cmp   r0, #0
        br.eq r12a
        brl   r10a, =putc
        adds  r2, r2, #1
        addc  r3, r3, #0
        br    =puts

; match: is the keyword at r6a the first word of the text at r2a?
; -> r1 = 1 and r2a behind the keyword, or r1 = 0.  Returns through r10a.
match:
        ldr   r1, r6a
        cmp   r1, #0
        br.eq .f =keyword_end
        ldr   r0, r2a
        cmp   r0, r1
        br.ne .f =no_match
        adds  r2, r2, #1
        addc  r3, r3, #0
        adds  r6, r6, #1
        addc  r7, r7, #0
        br    =match
.l keyword_end:
        ldr   r0, r2a           ; the word in the text has to end here as well
        mov   r1, #1
        cmp   r0, #' '
        br.eq r10a
        cmp   r0, #0
        br.eq r10a
.l no_match:
        mov   r1, #0
        br    r10a

; print_dec: send r4a as a decimal number.  Returns through r12a.
; Uses r0, r1, r2 (digit seen), r3 (places left), r6a, r8, r9 and destroys r4a.
print_dec:
        mova  r6a, =powers_of_10
        mov   r3, #4
        mov   r2, #0
.l place:
        ldr   r8, r6a           ; r9:r8 = 10000, 1000, 100, 10
        adds  r6, r6, #1
        addc  r7, r7, #0
        ldr   r9, r6a
        adds  r6, r6, #1
        addc  r7, r7, #0
        mov   r0, #'0'
.l again:
        cmp   r5, r9            ; r4a < r9:r8 ?
        br.su .f =emit
        br.ne .f =take
        cmp   r4, r8
        br.su .f =emit
.l take:
        subs  r4, r4, r8        ; r4a = r4a - r9:r8, the borrow by hand
        sub.su r5, r5, #1
        sub   r5, r5, r9
        add   r0, r0, #1
        br    .b =again
.l emit:
        cmp   r0, #'0'          ; no leading zeros
        br.ne .f =show
        cmp   r2, #0
        br.eq .f =skip
.l show:
        mov   r2, #1
        brl   r10a, =putc
.l skip:
        subs  r3, r3, #1
        br.ne .b =place
        add   r0, r4, #'0'      ; the ones are always printed
        brl   r10a, =putc
        br    r12a

; ---- data -----------------------------------------------------------------

.data
powers_of_10:   .dword #10000, #1000, #100, #10

kw_echo:        .asciz "echo"
kw_sum:         .asciz "sum"

msg_banner:     .asciz "\r\nSRA-8 terminal\r\n"
msg_prompt:     .asciz "> "
msg_newline:    .asciz "\r\n"
msg_unknown:    .asciz "commands: echo <text>, sum <n> <n> ...\r\n"
msg_bad_number: .asciz "sum: not a number\r\n"

line:           .res #81        ; LINE_MAX characters and the terminating zero
