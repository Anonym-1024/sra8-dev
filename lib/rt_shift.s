; rt_shift.s -- shifts by a run-time count (ABI of spec 7.7).
;
;   uint16 __shl16(uint16 v, uint8 n)      v << n
;   uint16 __shr16(uint16 v, uint8 n)      v >> n, zeros shifted in
;   int16  __sar16(int16 v, uint8 n)       v >> n, sign kept
;   and __shl32, __shr32, __sar32 with a 32 bit v
;
; A count of 16 (32) or more gives 0, or -1 / 0 for __sar.  Each shifts one
; bit per pass, so a count of n costs n passes.

        .export __shl16, __shr16, __sar16, __shl32, __shr32, __sar32

        .code
; load v -> r0a and n -> r2 for the 16 bit routines
__shl16:
        mov   r9, #0
        br    =shift16
__shr16:
        mov   r9, #1
        br    =shift16
__sar16:
        mov   r9, #2
shift16:
        adds  r6, r14, #1
        addc  r7, r15, #0
        ldr   r0, r6a
        adds  r6, r6, #1
        addc  r7, r7, #0
        ldr   r1, r6a
        adds  r6, r6, #1
        addc  r7, r7, #0
        ldr   r2, r6a
.l pass:
        cmp   r2, #0
        br.eq r12a
        sub   r2, r2, #1
        cmp   r9, #1
        br.eq .f =right
        br.gu .f =arith
        lsls  r0, r0
        csl   r1, r1
        br    .b =pass
.l right:
        lsrs  r1, r1
        csr   r0, r0
        br    .b =pass
.l arith:
        asrs  r1, r1
        csr   r0, r0
        br    .b =pass

; v -> r0..r3, n -> r4 for the 32 bit routines
__shl32:
        mov   r9, #0
        br    =shift32
__shr32:
        mov   r9, #1
        br    =shift32
__sar32:
        mov   r9, #2
shift32:
        adds  r6, r14, #1
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
        ldr   r4, r6a
.l pass32:
        cmp   r4, #0
        br.eq r12a
        sub   r4, r4, #1
        cmp   r9, #1
        br.eq .f =right32
        br.gu .f =arith32
        lsls  r0, r0
        csls  r1, r1
        csls  r2, r2
        csl   r3, r3
        br    .b =pass32
.l right32:
        lsrs  r3, r3
        csrs  r2, r2
        csrs  r1, r1
        csr   r0, r0
        br    .b =pass32
.l arith32:
        asrs  r3, r3
        csrs  r2, r2
        csrs  r1, r1
        csr   r0, r0
        br    .b =pass32
