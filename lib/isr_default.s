; isr_default.s -- the interrupt handler of a program that defines none.
;
; Link it when no 'interrupt' function exists; linking it together with
; one is a duplicate export of __isr.

        .export __isr

        .code
__isr:  intrw #0                  ; clear INTR: leaves interrupt mode
