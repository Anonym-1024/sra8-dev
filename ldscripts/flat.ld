; flat.ld -- the layout of the legacy assembler: everything from address 0,
; code first, then data, then bss.  Used by the golden tests and the
; sample programs (examples/asm).

memory all  start 0x0000  size 0x10000

place all
    code *
    data *
    bss *
end
