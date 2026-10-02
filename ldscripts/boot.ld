; boot.ld -- a program in the boot ROM, privilege level 0, owning the whole
; machine.  This is the default script of sra8-ld.
;
; At reset the control unit copies the 4 KiB boot ROM to address 0 and
; starts there, so code and data go into the first 4 KiB.  RAM above it is
; not initialised: crt0 zeroes the bss and the stack grows down from the
; top of RAM.

memory boot  start 0x0000  size 0x1000     ; copied from the boot ROM at reset
memory ram   start 0x1000  size 0xF000     ; uninitialised RAM

place boot
    code vector                            ; crt0's first instruction: address 0
    code *                                 ; every code section not placed yet
    data *
end

place ram
    symbol __bss_start                     ; = current address
    bss *
    symbol __bss_end
end

symbol __stack_top = last ram              ; 0xFFFF
