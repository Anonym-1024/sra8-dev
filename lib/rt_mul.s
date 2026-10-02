; rt_mul.s -- multiplication (ABI of spec 7.7: arguments on the stack,
; first argument at SP + 1, result in r0..r3, return through r12a).
;
;   uint16 __mul16(uint16 a, uint16 b)     low 16 bits of a * b
;   uint32 __mul32(uint32 a, uint32 b)     low 32 bits of a * b
;
; The low bits of a product do not depend on the signs, so these serve
; signed and unsigned operands alike.  8 bit products use __mul16.

        .export __mul16, __mul32

        .code
__mul16:
        adds  r8, r14, #1         ; r8a = address of a
        addc  r9, r15, #0
        ldr   r4, r8a             ; r4a = a, shifted left
        adds  r8, r8, #1
        addc  r9, r9, #0
        ldr   r5, r8a
        adds  r8, r8, #1
        addc  r9, r9, #0
        ldr   r6, r8a             ; r6a = b, shifted right
        adds  r8, r8, #1
        addc  r9, r9, #0
        ldr   r7, r8a
        mov   r0, #0              ; r0a = product
        mov   r1, #0
        mov   r8, #16
.l bit:
        lsrs  r7, r7              ; C = lowest bit of b
        csrs  r6, r6
        br.su .f =skip            ; su: C clear
        adds  r0, r0, r4
        addc  r1, r1, r5
.l skip:
        lsls  r4, r4
        csl   r5, r5
        subs  r8, r8, #1
        br.ne .b =bit
        br    r12a

; __mul32 needs 13 registers: it saves the frame pointer r10a and the link
; register r12a on the stack and restores them before returning.
__mul32:
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
        adds  r12, r14, #5        ; r12a = address of a (4 bytes pushed)
        addc  r13, r15, #0
        ldr   r4, r12a            ; r4..r7 = a, shifted left
        adds  r12, r12, #1
        addc  r13, r13, #0
        ldr   r5, r12a
        adds  r12, r12, #1
        addc  r13, r13, #0
        ldr   r6, r12a
        adds  r12, r12, #1
        addc  r13, r13, #0
        ldr   r7, r12a
        adds  r12, r12, #1
        addc  r13, r13, #0
        ldr   r8, r12a            ; r8..r11 = b, shifted right
        adds  r12, r12, #1
        addc  r13, r13, #0
        ldr   r9, r12a
        adds  r12, r12, #1
        addc  r13, r13, #0
        ldr   r10, r12a
        adds  r12, r12, #1
        addc  r13, r13, #0
        ldr   r11, r12a
        mov   r0, #0              ; r0..r3 = product
        mov   r1, #0
        mov   r2, #0
        mov   r3, #0
        mov   r12, #32
.l bit32:
        lsrs  r11, r11            ; C = lowest bit of b
        csrs  r10, r10
        csrs  r9, r9
        csrs  r8, r8
        br.su .f =skip32
        adds  r0, r0, r4
        addcs r1, r1, r5
        addcs r2, r2, r6
        addc  r3, r3, r7
.l skip32:
        lsls  r4, r4
        csls  r5, r5
        csls  r6, r6
        csl   r7, r7
        subs  r12, r12, #1
        br.ne .b =bit32
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
