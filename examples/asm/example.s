

; SRA-8 terminal: a line based command prompt on the UART port.
;
;       echo <text>             prints <text>
;       sum <n> <n> ...         prints the sum of the decimal numbers (16 bit, wraps at 65536)
;
; A line ends with CR or LF, backspace deletes the last character.
;
; Assemble with:  asm/sra8asm terminal.s -o program.mem
;
; Receiving: the port raises the IRQ for every byte.  The interrupt handler
; puts the byte into a 256 byte ring buffer, getc takes it out again, so a
; whole line may arrive at once while the CPU is still busy printing.
;
; Sending: the port has no busy flag, putc waits out one byte time instead.
;
; Registers
;       r0              character argument / result
;       r1              scratch of the leaf routines
;       r2a  (r2:r3)    text pointer; r2 alone is the length of the input line
;       r4a  (r4:r5)    16 bit sum
;       r6a  (r6:r7)    second pointer, number being parsed
;       r8, r9          16 bit temporary
;       r10a (r10:r11)  return address of the leaf routines (getc, putc, match)
;       r12a (r12:r13)  return address of puts and print_dec, which call putc
;       r14a (r14:r15)  ring buffer write pointer, owned by the interrupt handler

!DEFINE LINE_PAGE #0x0E         ; input line at 0x0E00
!DEFINE RING_PAGE #0x0F         ; ring buffer at 0x0F00..0x0FFF, the index wraps by itself
!DEFINE LINE_MAX  #80
!DEFINE TX_WAIT   #96           ; putc delay = 256 - 96 passes, about 1.6 ms (one byte is 1.04 ms)

.code
        mov   r14, #0
        mov   r15, !RING_PAGE
        intpcw =handler
        psrw  #0x20             ; irqm = 1 (IRQ enabled), pl = 0

        mova  r2a, =msg_banner
        brl   r12a, =puts



prompt:
        mova  r2a, =msg_prompt
        brl   r12a, =puts
        mov   r2, #0            ; r2a = start of the line, which is page aligned,
        mov   r3, !LINE_PAGE    ; so r2 is also the number of characters typed

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
        cmp   r2, !LINE_MAX
        br.geu =read_char       ; line full, drop the character
        str   r0, r2a
        add   r2, r2, #1
        brl   r10a, =putc       ; echo it
        br    =read_char

backspace:
        cmp   r2, #0
        br.eq =read_char
        sub   r2, r2, #1
        mov   r0, #8            ; step back, overwrite with a space, step back
        brl   r10a, =putc
        mov   r0, #' '
        brl   r10a, =putc
        mov   r0, #8
        brl   r10a, =putc
        br    =read_char

line_end:
        cmp   r2, #0            ; empty line, also the LF of a CR LF pair
        br.eq =read_char
        mov   r0, #0
        str   r0, r2a           ; terminate the line
        mova  r2a, =msg_newline
        brl   r12a, =puts

        mov   r2, #0
        mov   r3, !LINE_PAGE
        mova  r6a, =kw_echo
        brl   r10a, =match
        cmp   r1, #1
        br.eq =cmd_echo

        mov   r2, #0
        mov   r3, !LINE_PAGE
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
        add.eq r2, r2, #1
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
        add   r2, r2, #1
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
        add   r2, r2, #1
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
        ldr   r0, =ring_tail
        cmp   r0, r14           ; read index == write index: nothing there yet
        br.eq =getc
        add   r1, r0, #1
        str   r1, =ring_tail
        mov   r1, !RING_PAGE
        ldr   r0, r0a           ; r0 = ring[r0]
        br    r10a

; putc: send r0.  Returns through r10a, uses r1.
putc:
        ptw   r0
        mov   r1, !TX_WAIT
.l wait:
        adds  r1, r1, #1
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

; ---- interrupt handler ----------------------------------------------------
; Runs for every received byte.  It owns r14a and saves r0; none of its
; instructions change the flags.  INTPC stops behind intrw, so the branch
; back is the first instruction of the next interrupt.

handler:
        str   r0, =saved_r0
        ptr   r0                ; read the byte, this drops the port's IRQ
        str   r0, r14a
        add   r14, r14, #1
        ldr   r0, =saved_r0
        intrw #0                ; clear INTR, the CPU leaves interrupt mode here
        br    =handler

; ---- data -----------------------------------------------------------------

.data
ring_tail:      .word #0        ; ring buffer read index
saved_r0:       .word #0

powers_of_10:   .dword #10000, #1000, #100, #10

kw_echo:        .asciz "echo"
kw_sum:         .asciz "sum"

msg_banner:     .asciz "\r\nSRA-8 terminal\r\n"
msg_prompt:     .asciz "> "
msg_newline:    .asciz "\r\n"
msg_unknown:    .asciz "commands: echo <text>, sum <n> <n> ...\r\n"
msg_bad_number: .asciz "sum: not a number\r\n"


