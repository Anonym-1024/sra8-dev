; rt_div.s -- division and remainder (ABI of spec 7.7).
;
;   uint16 __divu16(uint16 a, uint16 b)    a / b
;   uint16 __modu16(uint16 a, uint16 b)    a % b
;   int16  __divs16(int16 a, int16 b)      a / b, rounded toward zero
;   int16  __mods16(int16 a, int16 b)      a % b, sign of a
;   and the same four with 32 bit operands: __divu32 __modu32 __divs32 __mods32
;
; Division by zero is undefined; these return quotient 0xFFFF.. and
; remainder a.  All share one restoring-division loop per width.  The
; entry points only set a mode in r9:
;   bit 0  return the remainder instead of the quotient
;   bit 1  negate the quotient          (signed: the signs differ)
;   bit 2  negate the remainder         (signed: a is negative)
;   bit 3  signed operands

        .export __divu16, __modu16, __divs16, __mods16
        .export __divu32, __modu32, __divs32, __mods32

        .code
__divu16:
        mov   r9, #0
        br    =div16
__modu16:
        mov   r9, #1
        br    =div16
__divs16:
        mov   r9, #8
        br    =div16
__mods16:
        mov   r9, #9

; 16 bit: dividend / quotient r0a, remainder r2a, divisor r4a, counter r8
div16:
        adds  r6, r14, #1         ; r6a = address of a
        addc  r7, r15, #0
        ldr   r0, r6a
        adds  r6, r6, #1
        addc  r7, r7, #0
        ldr   r1, r6a
        adds  r6, r6, #1
        addc  r7, r7, #0
        ldr   r4, r6a
        adds  r6, r6, #1
        addc  r7, r7, #0
        ldr   r5, r6a
        andd  r9, #8
        br.eq .f =unsigned
        andd  r1, #0x80           ; a negative?
        br.eq .f =a_positive
        eor   r0, r0, #0xFF
        eor   r1, r1, #0xFF
        adds  r0, r0, #1
        addc  r1, r1, #0
        eor   r9, r9, #6          ; flip the quotient sign, set the remainder sign
.l a_positive:
        andd  r5, #0x80           ; b negative?
        br.eq .f =unsigned
        eor   r4, r4, #0xFF
        eor   r5, r5, #0xFF
        adds  r4, r4, #1
        addc  r5, r5, #0
        eor   r9, r9, #2
.l unsigned:
        mov   r2, #0
        mov   r3, #0
        mov   r8, #16
.l bit:
        lsls  r0, r0              ; remainder:quotient <<= 1
        csls  r1, r1
        csls  r2, r2
        csls  r3, r3
        br.geu .f =take           ; bit 16 set: the remainder exceeds the divisor
        cmp   r2, r4              ; remainder >= divisor?
        subcd r3, r5
        br.su .f =next
.l take:
        subs  r2, r2, r4
        subc  r3, r3, r5
        or    r0, r0, #1
.l next:
        subs  r8, r8, #1
        br.ne .b =bit
        andd  r9, #1
        br.eq .f =quotient
        mov   r0, r2              ; remainder
        mov   r1, r3
        andd  r9, #4
        br.eq r12a
        br    .f =negate
.l quotient:
        andd  r9, #2
        br.eq r12a
.l negate:
        eor   r0, r0, #0xFF
        eor   r1, r1, #0xFF
        adds  r0, r0, #1
        addc  r1, r1, #0
        br    r12a

; 32 bit: dividend / quotient r0..r3, remainder r4..r7, divisor r8..r11,
; counter r12, mode r13.  Saves r10a and r12a on the stack.
__divu32:
        mov   r9, #0
        br    =div32
__modu32:
        mov   r9, #1
        br    =div32
__divs32:
        mov   r9, #8
        br    =div32
__mods32:
        mov   r9, #9

div32:
        str   r13, r14a           ; push r13, r12, r11, r10
        subs  r14, r14, #1
        subc  r15, r15, #0
        str   r12, r14a
        subs  r14, r14, #1
        subc  r15, r15, #0
        str   r11, r14a
        subs  r14, r14, #1
        subc  r15, r15, #0
        str   r10, r14a
        subs  r14, r14, #1
        subc  r15, r15, #0
        mov   r13, r9             ; mode
        adds  r6, r14, #5         ; r6a = address of a (4 bytes pushed)
        addc  r7, r15, #0
        ldr   r0, r6a
        adds  r6, r6, #1
        addc  r7, r7, #0
        ldr   r1, r6a
        adds  r6, r6, #1
        addc  r7, r7, #0
        ldr   r2, r6a
        adds  r6, r6, #1
        addc  r7, r7, #0
        ldr   r3, r6a
        adds  r6, r6, #1
        addc  r7, r7, #0
        ldr   r8, r6a
        adds  r6, r6, #1
        addc  r7, r7, #0
        ldr   r9, r6a
        adds  r6, r6, #1
        addc  r7, r7, #0
        ldr   r10, r6a
        adds  r6, r6, #1
        addc  r7, r7, #0
        ldr   r11, r6a
        andd  r13, #8
        br.eq .f =unsigned32
        andd  r3, #0x80           ; a negative?
        br.eq .f =a_positive32
        eor   r0, r0, #0xFF
        eor   r1, r1, #0xFF
        eor   r2, r2, #0xFF
        eor   r3, r3, #0xFF
        adds  r0, r0, #1
        addcs r1, r1, #0
        addcs r2, r2, #0
        addc  r3, r3, #0
        eor   r13, r13, #6
.l a_positive32:
        andd  r11, #0x80          ; b negative?
        br.eq .f =unsigned32
        eor   r8, r8, #0xFF
        eor   r9, r9, #0xFF
        eor   r10, r10, #0xFF
        eor   r11, r11, #0xFF
        adds  r8, r8, #1
        addcs r9, r9, #0
        addcs r10, r10, #0
        addc  r11, r11, #0
        eor   r13, r13, #2
.l unsigned32:
        mov   r4, #0
        mov   r5, #0
        mov   r6, #0
        mov   r7, #0
        mov   r12, #32
.l bit32:
        lsls  r0, r0
        csls  r1, r1
        csls  r2, r2
        csls  r3, r3
        csls  r4, r4
        csls  r5, r5
        csls  r6, r6
        csls  r7, r7
        br.geu .f =take32
        cmp   r4, r8
        subcd r5, r9
        subcd r6, r10
        subcd r7, r11
        br.su .f =next32
.l take32:
        subs  r4, r4, r8
        subcs r5, r5, r9
        subcs r6, r6, r10
        subc  r7, r7, r11
        or    r0, r0, #1
.l next32:
        subs  r12, r12, #1
        br.ne .b =bit32
        andd  r13, #1
        br.eq .f =quotient32
        mov   r0, r4
        mov   r1, r5
        mov   r2, r6
        mov   r3, r7
        andd  r13, #4
        br.eq .f =return32
        br    .f =negate32
.l quotient32:
        andd  r13, #2
        br.eq .f =return32
.l negate32:
        eor   r0, r0, #0xFF
        eor   r1, r1, #0xFF
        eor   r2, r2, #0xFF
        eor   r3, r3, #0xFF
        adds  r0, r0, #1
        addcs r1, r1, #0
        addcs r2, r2, #0
        addc  r3, r3, #0
.l return32:
        adds  r14, r14, #1        ; pop r10, r11, r12, r13
        addc  r15, r15, #0
        ldr   r10, r14a
        adds  r14, r14, #1
        addc  r15, r15, #0
        ldr   r11, r14a
        adds  r14, r14, #1
        addc  r15, r15, #0
        ldr   r12, r14a
        adds  r14, r14, #1
        addc  r15, r15, #0
        ldr   r13, r14a
        br    r12a
