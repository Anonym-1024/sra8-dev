; Board demo: binary counter on the port, about one step per second at 12 MHz
; (65536 passes of a 3 instruction delay loop, ~55 clock cycles per instruction)

.code
.l count:
        add   r1, r1, #1
        ptw   r1

        mova  r2a, #0             ; r2a = 16 bit delay counter
.l wait:
        adds  r2, r2, #1
        addcs r3, r3, #0          ; carry out of the high byte ends the loop
        br.su .b =wait            ; su = carry clear

        br    .b =count

