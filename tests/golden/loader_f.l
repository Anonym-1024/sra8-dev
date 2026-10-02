0000  00 D0 00 A4              intpcw =enter_program
0004  01 90 00 00              intrw #0
0008  00 32 01 00              mova  r2a, =msg_banner
000C  06 BC 00 E4              brl   r12a, =puts
0010  06 BA 00 B8              brl   r10a, =getc
0014  05 50 00 A5              cmp   r0, #0xA5
0018  96 90 00 10              br.ne .b =wait_mark
001C  06 BA 00 B8              brl   r10a, =getc
0020  00 06 00 00              mov   r6, r0
0024  06 BA 00 B8              brl   r10a, =getc
0028  00 07 00 00              mov   r7, r0
002C  00 09 70 00              mov   r9, r7
0030  05 56 00 00              cmp   r6, #0
0034  92 19 90 01              add.ne r9, r9, #1
0038  02 19 90 01              add   r9, r9, #1
003C  00 32 04 00              mova  r2a, #0x0400
0040  00 18 00 00              mov   r8, #0
0044  03 61 67 00              ors   r1, r6, r7
0048  16 90 00 6C              br.eq .f =received
004C  06 BA 00 B8              brl   r10a, =getc
0050  01 E0 20 00              str   r0, r2a
0054  02 08 80 00              add   r8, r8, r0
0058  02 32 20 01              adds  r2, r2, #1
005C  02 53 30 00              addc  r3, r3, #0
0060  02 B6 60 01              subs  r6, r6, #1
0064  42 97 70 01              sub.su r7, r7, #1
0068  06 90 00 44              br    .b =receive
006C  00 32 02 00              mova  r2a, #0x0200
0070  00 14 00 04              mov   r4, #4
0074  00 15 00 00              mov   r5, #0
0078  01 E4 20 00              str   r4, r2a
007C  02 12 20 01              add   r2, r2, #1
0080  01 E5 20 00              str   r5, r2a
0084  02 12 20 01              add   r2, r2, #1
0088  02 14 40 01              add   r4, r4, #1
008C  02 B9 90 01              subs  r9, r9, #1
0090  96 90 00 78              br.ne .b =map
0094  00 00 80 00              mov   r0, r8
0098  06 BA 00 D4              brl   r10a, =delay
009C  06 BA 00 D0              brl   r10a, =putc
00A0  07 00 00 00              svc
00A4  01 50 00 01              ptbrw #1
00A8  00 50 00 00              pcw   #0x0000
00AC  01 10 00 40              psrw  #0x40
00B0  01 90 00 00              intrw #0
00B4  06 90 00 A4              br    =enter_program
00B8  01 A1 00 00              intrr r1
00BC  05 91 00 10              andd  r1, #0x10
00C0  16 90 00 B8              br.eq =getc
00C4  06 C0 00 00              ptr   r0
00C8  01 90 00 00              intrw #0
00CC  06 8A 00 00              br    r10a
00D0  06 E0 00 00              ptw   r0
00D4  00 11 00 60              mov   r1, #96
00D8  02 31 10 01              adds  r1, r1, #1
00DC  46 90 00 D8              br.su .b =wait
00E0  06 8A 00 00              br    r10a
00E4  01 C0 20 00              ldr   r0, r2a
00E8  05 50 00 00              cmp   r0, #0
00EC  16 8C 00 00              br.eq r12a
00F0  06 BA 00 D0              brl   r10a, =putc
00F4  02 32 20 01              adds  r2, r2, #1
00F8  02 53 30 00              addc  r3, r3, #0
00FC  06 90 00 E4              br    =puts
0100  0D 0A 53 52 41 2D 38 20  .asciz "\r\nSRA-8 loader: waiting for a program\r\n"
0108  6C 6F 61 64 65 72 3A 20
0110  77 61 69 74 69 6E 67 20
0118  66 6F 72 20 61 20 70 72
0120  6F 67 72 61 6D 0D 0A 00

00A4  enter_program
00B8  getc
00D0  putc
00D4  delay
00E4  puts
0100  msg_banner
