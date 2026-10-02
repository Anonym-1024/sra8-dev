; SRA-8 loader: receives a program over the UART port and starts it in
; privilege level 1 behind a page table.
;
; Assemble with:  asm/sra8asm loader.s -o program.mem
; The other end is arduino_loader/arduino_loader.ino, the program it sends is user_echo.s.
;
; Upload protocol, all bytes from the Arduino to the loader:
;       0xA5                    start mark, everything before it is ignored
;       length, low byte        number of program bytes
;       length, high byte
;       length program bytes
; The loader answers with one byte, the 8 bit sum of the program bytes, and
; then starts the program.
;
; Physical memory (4096 bytes, pages of 256 bytes)
;       0x0000 .. 0x01FF        this loader
;       0x0200 .. 0x03FF        page table: 256 entries of 2 bytes, PTBR = 1 (address = PTBR * 512)
;       0x0400 .. 0x0FFF        the program, 12 pages
;
; The program is linked at virtual address 0.  Page table entry n holds the
; physical page of virtual page n, so entry 0 = 4, entry 1 = 5, ...  Only
; the pages of the program and one more for its data are mapped.  There is
; no valid bit: the other entries stay 0 and point at physical page 0.
;
; The switch to the program has to happen in interrupt mode.  Translation
; is off there, and PC is not the running program counter (INTPC is), so
; PTBR, PSR and PC can be set up one after the other.  Leaving interrupt
; mode then continues at PC with the new privilege level and translation
; switched on, all at once.  svc is how the loader gets into interrupt mode.
;
; The IRQ stays masked.  INTR latches the port's IRQ anyway, so getc polls
; it with intrr, and so does the loaded program.
;
; Registers
;       r0              character
;       r1              scratch
;       r2a  (r2:r3)    pointer
;       r4, r5          page table entry, low and high byte
;       r6a  (r6:r7)    bytes left to receive, later pages left to map
;       r8              checksum
;       r9              number of pages to map
;       r10a (r10:r11)  return address of getc and putc
;       r12a (r12:r13)  return address of puts

!DEFINE START_MARK  #0xA5
!DEFINE INTR_IRQ    #0x10       ; IRQ bit of INTR, as read by intrr
!DEFINE TABLE       #0x0200     ; page table
!DEFINE TABLE_PTBR  #1          ; TABLE / 512
!DEFINE LOAD        #0x0400     ; physical address of the program
!DEFINE LOAD_PAGE   #4          ; LOAD / 256
!DEFINE USER_PSR    #0x40       ; pl = 1, IRQ masked, flags clear
!DEFINE TX_WAIT     #96         ; putc delay = 256 - 96 passes, about 1.6 ms (one byte is 1.04 ms)

.code
        intpcw =enter_program   ; where svc will end up
        intrw #0

        mova  r2a, =msg_banner
        brl   r12a, =puts

; ---- receive the program --------------------------------------------------

.l wait_mark:
        brl   r10a, =getc
        cmp   r0, !START_MARK
        br.ne .b =wait_mark

        brl   r10a, =getc
        mov   r6, r0            ; r6a = length
        brl   r10a, =getc
        mov   r7, r0

        mov   r9, r7            ; pages = length / 256, rounded up, + 1 for data
        cmp   r6, #0
        add.ne r9, r9, #1
        add   r9, r9, #1

        mova  r2a, !LOAD
        mov   r8, #0
.l receive:
        ors   r1, r6, r7        ; nothing left?
        br.eq .f =received
        brl   r10a, =getc
        str   r0, r2a
        add   r8, r8, r0
        adds  r2, r2, #1
        addc  r3, r3, #0
        subs  r6, r6, #1        ; r6a = r6a - 1, the borrow by hand
        sub.su r7, r7, #1
        br    .b =receive
.l received:

; ---- build the page table -------------------------------------------------

        mova  r2a, !TABLE
        mov   r4, !LOAD_PAGE
        mov   r5, #0
.l map:
        str   r4, r2a           ; entry = physical page, low byte first
        add   r2, r2, #1
        str   r5, r2a
        add   r2, r2, #1
        add   r4, r4, #1
        subs  r9, r9, #1
        br.ne .b =map

; ---- answer and start -----------------------------------------------------

        mov   r0, r8
        brl   r10a, =delay      ; let the sender finish its last stop bit and start listening
        brl   r10a, =putc
        svc                     ; -> enter_program, never comes back

; ---- interrupt mode -------------------------------------------------------
; The only interrupt that is not masked is svc.

enter_program:
        ptbrw !TABLE_PTBR
        pcw   #0x0000           ; entry point, a virtual address
        psrw  !USER_PSR
        intrw #0                ; leave interrupt mode: the next fetch is at PC, translated
        br    =enter_program    ; an svc of the program lands here and restarts it

; ---- subroutines ----------------------------------------------------------

; getc: wait for a received byte -> r0.  Returns through r10a, uses r1.
getc:
        intrr r1
        andd  r1, !INTR_IRQ
        br.eq =getc
        ptr   r0                ; read the byte, this drops the port's IRQ
        intrw #0                ; clear the latched IRQ
        br    r10a

; putc: send r0 and wait until it is out.  delay: only wait.
; Both return through r10a and use r1.
putc:
        ptw   r0
delay:
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

.data
msg_banner:     .asciz "\r\nSRA-8 loader: waiting for a program\r\n"
