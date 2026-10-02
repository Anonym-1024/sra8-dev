; rt_mem.s -- block copy and clear, used for struct and array values
; (ABI of spec 7.7).
;
;   void __copy(void* dst, void* src, uint16 n)    n bytes, ascending addresses
;   void __zero(void* dst, uint16 n)

        .export __copy, __zero

        .code
__copy:
        adds  r2, r14, #1         ; r2a walks over the arguments
        addc  r3, r15, #0
        ldr   r4, r2a             ; r4a = dst
        adds  r2, r2, #1
        addc  r3, r3, #0
        ldr   r5, r2a
        adds  r2, r2, #1
        addc  r3, r3, #0
        ldr   r6, r2a             ; r6a = src
        adds  r2, r2, #1
        addc  r3, r3, #0
        ldr   r7, r2a
        adds  r2, r2, #1
        addc  r3, r3, #0
        ldr   r8, r2a             ; r8a = n
        adds  r2, r2, #1
        addc  r3, r3, #0
        ldr   r9, r2a
.l copy:
        ors   r0, r8, r9
        br.eq r12a
        ldr   r0, r6a
        str   r0, r4a
        adds  r4, r4, #1
        addc  r5, r5, #0
        adds  r6, r6, #1
        addc  r7, r7, #0
        subs  r8, r8, #1
        subc  r9, r9, #0
        br    .b =copy

__zero:
        adds  r2, r14, #1
        addc  r3, r15, #0
        ldr   r4, r2a             ; r4a = dst
        adds  r2, r2, #1
        addc  r3, r3, #0
        ldr   r5, r2a
        adds  r2, r2, #1
        addc  r3, r3, #0
        ldr   r8, r2a             ; r8a = n
        adds  r2, r2, #1
        addc  r3, r3, #0
        ldr   r9, r2a
        mov   r0, #0
.l clear:
        ors   r1, r8, r9
        br.eq r12a
        str   r0, r4a
        adds  r4, r4, #1
        addc  r5, r5, #0
        subs  r8, r8, #1
        subc  r9, r9, #0
        br    .b =clear
