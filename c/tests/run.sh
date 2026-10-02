#!/bin/sh
# run.sh -- the test suite of the C port of the SRA-8 tools.
#
#   make test      or      sh tests/run.sh       (in the c folder)
#
# Needs the tools in c/bin/ (make) and a POSIX shell with cmp, od, grep and
# sed.  Examples, runtime, linker scripts, goldens, docs and the VS Code
# grammar are shared with the Python implementation one folder up.  The
# RTL check is skipped when ../sra-8-fpga/sra-8-fpga (next to the
# repository) is missing; set SRA8_RTL to point elsewhere.

set -u
CDIR=$(cd "$(dirname "$0")/.." && pwd)
ROOT=$(cd "$CDIR/.." && pwd)
AS=$CDIR/bin/sra8-as
LD=$CDIR/bin/sra8-ld
OD=$CDIR/bin/sra8-objdump
ISAGEN=$CDIR/bin/isagen
FLAT=$ROOT/ldscripts/flat.ld
BOOT=$ROOT/ldscripts/boot.ld
GOLDEN=$ROOT/tests/golden
RTL=${SRA8_RTL:-$ROOT/../sra-8-fpga/sra-8-fpga}

for t in "$AS" "$LD" "$OD" "$ISAGEN"; do
    [ -x "$t" ] || { echo "missing $t: run make first"; exit 2; }
done

T=$(mktemp -d "${TMPDIR:-/tmp}/sra8-test.XXXXXX") || exit 2
trap 'rm -rf "${T:?}"' EXIT

pass=0
fail=0
section() { printf '%s\n' "-- $1"; }
ok() { pass=$((pass + 1)); }
bad() {
    fail=$((fail + 1))
    printf 'FAIL %s\n' "$1"
    if [ $# -gt 1 ]; then printf '%s\n' "$2" | sed 's/^/     /'; fi
}

# src NAME: write stdin to $T/NAME.s
src() { cat > "$T/$1.s"; }
# script NAME: write stdin to $T/NAME.ld
script() { cat > "$T/$1.ld"; }
# hex bytes of a file, lower case, no spaces
hexof() { od -An -v -tx1 "$1" | tr -d ' \n'; }
norm() { printf '%s' "$1" | tr -d ' ' | tr 'A-F' 'a-f'; }

# asm_bytes NAME HEX: NAME.s assembles and links (flat.ld) to exactly HEX
asm_bytes() {
    if "$AS" "$T/$1.s" -o "$T/$1.o" 2> "$T/$1.err" && "$LD" -T "$FLAT" -o "$T/$1.bin" "$T/$1.o" 2>> "$T/$1.err"; then
        got=$(hexof "$T/$1.bin")
        want=$(norm "$2")
        if [ "$got" = "$want" ]; then ok; else bad "$1: got $got, want $want"; fi
    else
        bad "$1: does not assemble" "$(cat "$T/$1.err")"
    fi
}

# asm_fails NAME TEXT...: assembling NAME.s fails and the messages contain every TEXT
asm_fails() {
    n=$1
    shift
    if "$AS" "$T/$n.s" -o "$T/$n.o" 2> "$T/$n.err"; then
        bad "$n: assembled, expected an error"
        return
    fi
    for t in "$@"; do
        if ! grep -qF -- "$t" "$T/$n.err"; then
            bad "$n: missing '$t'" "$(cat "$T/$n.err")"
            return
        fi
    done
    ok
}

# asm_warns NAME TEXT: assembles, with a warning containing TEXT
asm_warns() {
    if "$AS" "$T/$1.s" -o "$T/$1.o" 2> "$T/$1.err" && grep -qF -- "$2" "$T/$1.err"; then ok; else
        bad "$1: expected warning '$2'" "$(cat "$T/$1.err")"
    fi
}

# obj NAME: assemble NAME.s to NAME.o, which must succeed
obj() { "$AS" "$T/$1.s" -o "$T/$1.o" 2> "$T/$1.err" || bad "$1: does not assemble" "$(cat "$T/$1.err")"; }

# ld_bytes NAME SCRIPT HEX OBJ...: links (SCRIPT is a file) to exactly HEX
ld_bytes() {
    n=$1 s=$2 want=$(norm "$3")
    shift 3
    if "$LD" -T "$s" -o "$T/$n.bin" -M "$T/$n.map" "$@" 2> "$T/$n.err"; then
        got=$(hexof "$T/$n.bin")
        if [ "$got" = "$want" ]; then ok; else bad "$n: got $got, want $want"; fi
    else
        bad "$n: does not link" "$(cat "$T/$n.err")"
    fi
}

# ld_fails NAME SCRIPT TEXT OBJ...: linking fails with a message containing TEXT
ld_fails() {
    n=$1 s=$2 t=$3
    shift 3
    if "$LD" -T "$s" -o "$T/$n.bin" "$@" 2> "$T/$n.err"; then
        bad "$n: linked, expected an error"
    elif grep -qF -- "$t" "$T/$n.err"; then ok; else
        bad "$n: missing '$t'" "$(cat "$T/$n.err")"
    fi
}

# ===========================================================================
section "instruction table"

if [ -d "$RTL" ]; then
    if "$ISAGEN" check-rtl "$RTL" > "$T/rtl.out" 2>&1; then ok; else bad "check-rtl" "$(cat "$T/rtl.out")"; fi
else
    echo "     (RTL folder $RTL not found, skipped)"
fi
"$ISAGEN" markdown > "$T/isa.md"
if cmp -s "$T/isa.md" "$ROOT/docs/isa.md"; then ok; else bad "docs/isa.md differs from isagen: the C and Python instruction tables disagree"; fi
"$ISAGEN" asm-grammar > "$T/grammar.json"
if cmp -s "$T/grammar.json" "$ROOT/vscode/sra8-lang/syntaxes/sra8-asm.tmLanguage.json"; then ok; else
    bad "the VS Code grammar differs from isagen: the C and Python instruction tables disagree"
fi

# ===========================================================================
section "encoding vectors (spec 2.7)"

vector() {
    printf '.code\n%s\n' "$2" > "$T/$1.s"
    asm_bytes "$1" "$3"
}
vector v1 "cmp r0, #0xA5" "05 50 00 A5"
vector v2 "add.ne r9, r9, #1" "92 19 90 01"
vector v3 "ors r1, r6, r7" "03 61 67 00"
vector v4 "str r0, r2a" "01 E0 20 00"
vector v5 "ldr r0, r2a" "01 C0 20 00"
vector v6 "br r10a" "06 8A 00 00"
vector v7 "svc" "07 00 00 00"
vector v8 "ptr r0" "06 C0 00 00"
vector v9 "ptw r0" "06 E0 00 00"
vector v10 "intrr r1" "01 A1 00 00"
vector v11 "psrw #0x40" "01 10 00 40"
vector v12 "sub.su r7, r7, #1" "42 97 70 01"
vector v13 "andd r1, #0x10" "05 91 00 10"
vector v14 "MOV R1, R2" "00 01 20 00"
vector v15 "mova r2a, #-1" "00 32 FF FF"
vector v16 "mov r3, #'a'" "00 13 00 61"

{
    i=0
    while [ $i -lt 41 ]; do echo "        .res 4"; i=$((i + 1)); done
    echo "enter_program: br =enter_program"
    echo "intpcw =enter_program"
    echo "brl r12a, =enter_program"
} > "$T/labels.s"
"$AS" "$T/labels.s" -o "$T/labels.o" && "$LD" -T "$FLAT" -o "$T/labels.bin" "$T/labels.o"
got=$(hexof "$T/labels.bin" | cut -c329-)
if [ "$got" = "069000a400d000a406bc00a4" ]; then ok; else bad "label vectors: $got"; fi

# ===========================================================================
section "legacy programs: byte-identical to the legacy assembler"

for n in echo loader terminal user_echo example demo; do
    "$AS" "$ROOT/examples/asm/$n.s" -o "$T/$n.o" 2> "$T/$n.err" || { bad "$n: does not assemble" "$(cat "$T/$n.err")"; continue; }
    "$LD" -T "$FLAT" --format mem -o "$T/$n.mem" "$T/$n.o" && "$LD" -T "$FLAT" -o "$T/$n.bin" "$T/$n.o"
    for k in bin mem; do
        if cmp -s "$T/$n.$k" "$GOLDEN/$n.$k"; then ok; else bad "$n.$k differs from tests/golden"; fi
    done
done
# every line of the legacy listing f.l that shows bytes: the same bytes at that address
sed -n 's/^\([0-9A-F][0-9A-F][0-9A-F][0-9A-F]\)  \(\([0-9A-F][0-9A-F] \)*[0-9A-F][0-9A-F]\)  .*/\1 \2/p' "$GOLDEN/loader_f.l" > "$T/fl.txt"
fl_bad=0
fl_n=0
while read -r addr bytes; do
    n=$(printf '%s\n' "$bytes" | wc -w | tr -d ' ')
    got=$(od -An -v -tx1 -j $((0x$addr)) -N "$n" "$T/loader.bin" | tr -d ' \n')
    [ "$got" = "$(norm "$bytes")" ] || fl_bad=$((fl_bad + 1))
    fl_n=$((fl_n + 1))
done < "$T/fl.txt"
if [ "$fl_bad" -eq 0 ] && [ "$fl_n" -gt 50 ]; then ok; else bad "f.l: $fl_bad of $fl_n lines differ"; fi

# ===========================================================================
section "assembler: sections"

src sections << 'EOF'
first: mov r0, #0
.data
d: .byte 1
.code vector
v: mov r1, #1
.data rodata
.asciz "x"
.bss
b: .res 10
.code
mov r2, #2
EOF
obj sections
if "$OD" -t "$T/sections.o" | grep -q '\[4\] bss                 10 bytes' \
    && "$OD" -t "$T/sections.o" | grep -q '\[2\] code:vector          4 bytes' \
    && "$OD" -t "$T/sections.o" | grep -q '\[0\] code                 8 bytes'; then ok; else
    bad "section table" "$("$OD" -t "$T/sections.o")"
fi
printf '.data\n.byte 1\n' | src only_data
obj only_data
if "$OD" -t "$T/only_data.o" | grep -q '\[0\] data'; then ok; else bad "no implicit empty code section"; fi

printf '.data\nmov r0, #0\n' | src instr_in_data
asm_fails instr_in_data "instruction in a .data section"
printf '.bss\n.byte 1\n' | src bss_byte
asm_fails bss_byte "only .res"
printf '.bss\nmov r0, #0\n' | src bss_instr
asm_fails bss_instr "instruction in a .bss"
printf '.code\n.byte 1\nmov r0, #0\n' | src unaligned
asm_fails unaligned "unaligned offset 1"
printf '.code\n.byte 1, 2, 3, 4\nmov r0, #0\n' | src aligned
asm_bytes aligned "01 02 03 04 00 10 00 00"
printf '.code a b\n' | src badsec
asm_fails badsec "optional section name"

# ===========================================================================
section "assembler: removed features"

for d in ".org 0|linker script" ".align 4|linker script" ".global x|.export" ".extern x|.import" \
    ".weak x|weak" ".equ X, 1|!DEFINE" ".set X, 1|!DEFINE" ".section .text|.code" '.incbin "f"|not supported' \
    ".text|.code"; do
    printf '%s\n' "${d%%|*}" | src removed
    asm_fails removed "does not exist" "${d#*|}"
done
for p in "nop" "ret r12a" "halt" "movs r1, r2" "mvn r1, r2"; do
    printf '%s\n' "$p" | src pseudo
    asm_fails pseudo "not an SRA-8 instruction"
done
printf 'mov r0, #0 // no\n' | src c1
asm_fails c1 "only ';' starts a comment"
printf '/* no */\n' | src c2
asm_fails c2 "only ';' starts a comment"
printf '.data\n.asciz "a // b ; c"   ; fine\n' | src c3
asm_bytes c3 "61 20 2f 2f 20 62 20 3b 20 63 00"
printf 'mov r0, #1+2\n' | src e1
asm_fails e1 "expressions are not supported"
printf '.import a\nmova r0a, =a * 2\n' | src e2
asm_fails e2 "bad label reference"
printf 'br .\n' | src e3
asm_fails e3 "bad operand"
printf '!IFDEF X\n' | src pp
asm_fails pp "unknown preprocessor directive"

# ===========================================================================
section "assembler: linkage"

printf 'br =elsewhere\n' | src undef
asm_fails undef "undefined name 'elsewhere'" ".import elsewhere"
printf '.import f\nbrl r12a, =f + 4\n' | src imp
obj imp
if "$OD" -r -t "$T/imp.o" | grep -q 'IMM16  f +4' && "$OD" -t "$T/imp.o" | grep -qx '  f'; then ok; else
    bad "import relocation" "$("$OD" -r -t "$T/imp.o")"
fi
printf '.import f\nmov r0, #0\n' | src unused
asm_warns unused "never used"
printf '.import f\nf: br =f\n' | src impdef
asm_fails impdef "imported but also defined"
printf '.export nothing\n' | src expundef
asm_fails expundef "not defined"
printf '.import a\n.export a\nbr =a\n' | src expimp
asm_fails expimp "cannot be exported"
printf '.export x\n.l x: br .b =x\n' | src exploc
asm_fails exploc "local labels cannot be exported"
printf 'a: mov r0, #0\na: mov r0, #0\n' | src dup
asm_fails dup "already defined"
printf '.export f\nf: br =f\ng: br =g\n' | src exp
obj exp
if "$OD" -t "$T/exp.o" | grep -q '^  code+0000        f$' && ! "$OD" -t "$T/exp.o" | grep -q ' g$'; then ok; else
    bad "only exported labels are in the object" "$("$OD" -t "$T/exp.o")"
fi

# ===========================================================================
section "assembler: operands"

src locals << 'EOF'
.l x: mov r0, #0
br .b =x
br .f =x
.l x: br .b =x
EOF
asm_bytes locals "00 10 00 00  06 90 00 00  06 90 00 0C  06 90 00 0C"
printf '.l y: br .f =y\n' | src nolocal
asm_fails nolocal "no local label 'y' after"
printf '.l z: br =z\n' | src uselocal
asm_fails uselocal "use .b =z"
printf 'a: mova r2a, =a - 2\n.data\n.addr =a + 0x10, 7\n' | src minus
asm_bytes minus "00 32 FF FE  10 00 07 00"
printf 'a: mov r0, =a\n' | src imm8label
asm_fails imm8label "8 bit immediate"
printf 'a: mov r0, #0\n.data\n.byte =a\n' | src bytelabel
asm_fails bytelabel "use .addr"
printf 'mova r1, r2a\n' | src w1
asm_fails w1 "16 bit register pair"
printf 'mov r1a, r2\n' | src w2
asm_fails w2 "8 bit register"
printf 'str #1, r2a\n' | src w3
asm_fails w3 "must be a register"
printf 'br r15a\n' | src w4
asm_warns w4 "r15a"
printf 'mov r0, #256\n' | src r1
asm_fails r1 "does not fit in 8 bits"
printf 'mova r0a, #65536\n' | src r2
asm_fails r2 "does not fit in 16 bits"
printf 'mov r0, #-128\nmov r0, #255\n' | src r3
asm_bytes r3 "00 10 00 80  00 10 00 FF"
printf 'mov r0\n' | src r4
asm_fails r4 "takes 2 operands"
printf 'add.xx r0, r0, r0\n' | src r5
asm_fails r5 "unknown condition"
printf 'ADD.EQ R1, R2, #3\nBR R4A\n' | src case
asm_bytes case "12 11 20 03  06 84 00 00"
printf ".data\n.byte 0b101, 0o17, 0d9, 0x1F, '\\\\n', -1\n.dword 0x1234\n.qword 1\n" | src numbers
asm_bytes numbers "05 0f 09 1f 0a ff 34 12 01 00 00 00"

# ===========================================================================
section "assembler: preprocessor and messages"

mkdir -p "$T/inc"
printf '!DEFINE cnt r1\n!DEFINE LIMIT #0x10\n' > "$T/inc/regs.inc"
printf '!INCLUDE inc/regs.inc\nmov !cnt, !LIMIT\n' | src include
asm_bytes include "00 11 00 10"
printf 'mov r0, #0\nbogus r1\n' | src located
asm_fails located "located.s:2: error: unknown instruction 'bogus'"
printf '!INCLUDE missing.inc\n' | src noinc
asm_fails noinc "noinc.s:1: error: cannot read" "missing.inc'"
i=0
: > "$T/many.s"
while [ $i -lt 25 ]; do echo "bogus$i" >> "$T/many.s"; i=$((i + 1)); done
asm_fails many "error: too many errors, stopping"
if [ "$(grep -c 'error:' "$T/many.err")" = 21 ]; then ok; else bad "many: expected 20 errors and the stop line"; fi

printf '.import unused\nmov r0, #0\n' | src werr
if "$AS" "$T/werr.s" -o "$T/werr.o" 2> /dev/null && ! "$AS" -Werror "$T/werr.s" -o "$T/werr.o" 2> /dev/null; then ok; else
    bad "-Werror"
fi
"$AS" "$ROOT/examples/asm/terminal.s" -o "$T/d1.o" && "$AS" "$ROOT/examples/asm/terminal.s" -o "$T/d2.o"
if cmp -s "$T/d1.o" "$T/d2.o"; then ok; else bad "assembling is not deterministic"; fi
if "$AS" "$T/nothere.s" 2> "$T/nothere.err"; then bad "missing source accepted"; elif grep -qF "cannot read" "$T/nothere.err"; then ok; else
    bad "missing source message" "$(cat "$T/nothere.err")"
fi

# ===========================================================================
section "linker"

script bootish << 'EOF'
memory boot start 0x0000 size 0x100
memory ram  start 0x1000 size 0x100
place boot
    code vector
    code *
    data *
end
place ram
    symbol __bss_start
    bss *
    symbol __bss_end
end
symbol top = last ram
symbol base = start ram
symbol magic = 0x1234
EOF
printf '.import g\n.export f\nf: brl r12a, =g\n' | src la
printf '.import f\n.export g\ng: br =f\n' | src lb
obj la
obj lb
ld_bytes cross "$FLAT" "06 BC 00 04  06 90 00 00" "$T/la.o" "$T/lb.o"

printf '.code\nmov r0, #1\n.code vector\nmov r0, #2\n.data\n.byte 0xAA\n' | src lc
printf '.code\nmov r0, #3\n.data rodata\n.byte 0xBB\n.data\n.byte 0xCC\n' | src ld2
obj lc
obj ld2
ld_bytes order "$T/bootish.ld" "00 10 00 02  00 10 00 01  00 10 00 03  AA CC BB" "$T/lc.o" "$T/ld2.o"

src syms << 'EOF'
.import top, base, magic, __bss_start, __bss_end
mova r0a, =top
mova r0a, =base
mova r0a, =magic
mova r0a, =__bss_start
mova r0a, =__bss_end
.bss
.res 7
EOF
obj syms
ld_bytes syms "$T/bootish.ld" "00 30 10 FF 00 30 10 00 00 30 12 34 00 30 10 00 00 30 10 07" "$T/syms.o"

script dcalign << 'EOF'
memory m start 0 size 0x100
place m
    data *
    code *
    align 16
    symbol after
end
EOF
printf '.data\n.byte 1\n' | src data1
printf 'x: mov r0, #0\n' | src code1
obj data1
obj code1
ld_bytes align "$T/dcalign.ld" "01 00 00 00  00 10 00 00" "$T/data1.o" "$T/code1.o"
if grep -q '0x0010  after .*script' "$T/align.map"; then ok; else bad "align symbol" "$(cat "$T/align.map")"; fi

printf 'mov r0, #0\n.bss\n.res 100\n' | src bss100
obj bss100
ld_bytes bssimage "$FLAT" "00 10 00 00" "$T/bss100.o"
script gapscript << 'EOF'
memory m start 0 size 0x100
place m
    code *
    bss *
    data *
end
EOF
printf 'mov r0, #0\n.bss\n.res 4\n.data\n.byte 9\n' | src gap
obj gap
ld_bytes bssgap "$T/gapscript.ld" "00 10 00 00  00 00 00 00  09" "$T/gap.o"

printf '.export f\nf: br =f\n' | src expf
obj expf
ld_fails dupexp "$FLAT" "exported by both" "$T/expf.o" "$T/expf.o"
printf '.import nowhere\nbr =nowhere\n' | src nowhere
obj nowhere
ld_fails unresolved "$FLAT" "undefined symbol 'nowhere'" "$T/nowhere.o"
printf '.import f\nbr =f\n' | src impf
printf 'f: br =f\n' | src deff
obj impf
obj deff
ld_fails hidden "$FLAT" "undefined symbol 'f'" "$T/impf.o" "$T/deff.o"
printf 'memory m start 0 size 16\nplace m\n code\nend\n' | script onlycode
printf '.code special\nmov r0, #0\n' | src special
obj special
ld_fails unplaced "$T/onlycode.ld" "code:special" "$T/special.o"
printf 'memory m start 0 size 16\nplace m\n data *\nend\n' | script small
printf '.data\n.res 20\n' | src big
obj big
ld_fails overflow "$T/small.ld" "does not fit into region 'm'" "$T/big.o"
printf '.export top\ntop: br =top\n' | src exptop
obj exptop
ld_fails clash "$T/bootish.ld" "also exported" "$T/exptop.o"

for c in "memory a start 0 size 0x10|memory b start 8 size 0x10|overlaps" \
    "memory a start 0xFFF0 size 0x20||within 0x0000" \
    "place nowhere|end|unknown region" \
    "memory a start 0 size 16|place a|not closed" \
    "code *||only allowed inside" \
    "symbol x = 1 + 2||expected  symbol" \
    "memory a start 0 size zz||bad number"; do
    l1=${c%%|*}
    rest=${c#*|}
    l2=${rest%%|*}
    want=${rest#*|}
    printf '%s\n%s\n' "$l1" "$l2" > "$T/bad.ld"
    ld_fails "script: $want" "$T/bad.ld" "$want" "$T/code1.o"
done

printf 'memory a start 0b10 size 0x10 ; c\nplace a\n code *\nend\n' | script comments
# the region starts at 2, code at the next multiple of 4
ld_bytes comments "$T/comments.ld" "00 00 00 10 00 00" "$T/code1.o"

printf '.data\n.byte 1, 2, 3\n' | src data3
obj data3
printf 'memory m start 0x100 size 16\nplace m\n data\nend\n' | script at100
if "$LD" -T "$T/at100.ld" --format ihex -o "$T/x.hex" "$T/data3.o" \
    && [ "$(cat "$T/x.hex")" = ":03010000010203F6
:00000001FF" ]; then ok; else bad "ihex" "$(cat "$T/x.hex" 2> /dev/null)"; fi
if "$LD" -T "$T/at100.ld" --format mem -o "$T/x.mem" "$T/data3.o" 2> "$T/x.err"; then bad "mem accepted an image not at 0"; else ok; fi
printf 'mov r0, #0x5A\n' | src m1
obj m1
if "$LD" -T "$FLAT" --format mem --mem-size 8 -o "$T/m1.mem" "$T/m1.o" \
    && [ "$(cat "$T/m1.mem")" = "@0000
00 10 00 5A
00 00 00 00" ]; then ok; else bad "mem format" "$(cat "$T/m1.mem" 2> /dev/null)"; fi

# ===========================================================================
section "disassembler round trips"

for n in echo loader terminal user_echo example demo; do
    "$OD" "$T/$n.bin" > "$T/$n.dis.s"
    "$AS" "$T/$n.dis.s" -o "$T/$n.dis.o" && "$LD" -T "$FLAT" -o "$T/$n.rt.bin" "$T/$n.dis.o"
    if cmp -s "$T/$n.rt.bin" "$T/$n.bin"; then ok; else bad "$n: image round trip"; fi
    "$OD" "$T/$n.o" > "$T/$n.odis.s"
    "$AS" "$T/$n.odis.s" -o "$T/$n.odis.o" && "$LD" -T "$FLAT" -o "$T/$n.ort.bin" "$T/$n.odis.o"
    if cmp -s "$T/$n.ort.bin" "$T/$n.bin"; then ok; else bad "$n: object round trip"; fi
    "$OD" "$T/$n.mem" > "$T/$n.mdis.s"
    "$AS" "$T/$n.mdis.s" -o "$T/$n.mdis.o" && "$LD" -T "$FLAT" --format mem -o "$T/$n.mrt.mem" "$T/$n.mdis.o"
    if cmp -s "$T/$n.mrt.mem" "$T/$n.mem"; then ok; else bad "$n: .mem round trip"; fi
done
i=0
: > "$T/garbage.bin"
while [ $i -lt 259 ]; do
    # shellcheck disable=SC2059
    printf "\\$(printf '%03o' $((i % 256)))" >> "$T/garbage.bin"
    i=$((i + 1))
done
"$OD" "$T/garbage.bin" > "$T/garbage.s"
"$AS" "$T/garbage.s" -o "$T/garbage.o" && "$LD" -T "$FLAT" -o "$T/garbage.rt" "$T/garbage.o"
if cmp -s "$T/garbage.rt" "$T/garbage.bin"; then ok; else bad "arbitrary bytes round trip"; fi
printf '.export a\na: mov r0, #0\n.addr =a, =a\nbr =a\n' | src addrcode
obj addrcode
"$LD" -T "$FLAT" -o "$T/addrcode.bin" "$T/addrcode.o"
"$OD" "$T/addrcode.o" > "$T/addrcode.dis.s"
"$AS" "$T/addrcode.dis.s" -o "$T/addrcode2.o" && "$LD" -T "$FLAT" -o "$T/addrcode2.bin" "$T/addrcode2.o"
if cmp -s "$T/addrcode.bin" "$T/addrcode2.bin"; then ok; else bad ".addr inside code round trip"; fi
printf '.bss\nstart: .res 4\nend:\n' | src bssend
obj bssend
"$OD" "$T/bssend.o" > "$T/bssend.dis.s"
if "$AS" "$T/bssend.dis.s" -o "$T/bssend2.o" 2> "$T/bssend.err"; then ok; else bad "bss label at the end" "$(cat "$T/bssend.err")"; fi

# ===========================================================================
section "runtime and start-up code"

objs=""
for f in crt0 isr_default uart rt_mul rt_div rt_shift rt_mem; do
    if "$AS" -Werror "$ROOT/lib/$f.s" -o "$T/rt_$f.o" 2> "$T/rt_$f.err"; then ok; else bad "lib/$f.s" "$(cat "$T/rt_$f.err")"; fi
done
"$AS" "$ROOT/examples/rt/hello.s" -o "$T/hello.o"
if "$LD" -T "$BOOT" -o "$T/hello.bin" -M "$T/hello.map" "$T/rt_crt0.o" "$T/hello.o" "$T/rt_isr_default.o" "$T/rt_uart.o" \
    "$T/rt_rt_mul.o" "$T/rt_rt_div.o" "$T/rt_rt_shift.o" "$T/rt_rt_mem.o" 2> "$T/hello.err"; then
    ok
    [ "$(hexof "$T/hello.bin" | cut -c1-4)" = 00d0 ] && ok || bad "intpcw is not at address 0"
    for s in "0x0000  _start" "0xFFFF  __stack_top" "__mul32" "__divs16" "__sar32" "__copy" "uart_puts" "__isr" "main"; do
        if grep -qF "$s" "$T/hello.map"; then ok; else bad "hello.map lacks $s"; fi
    done
else
    bad "hello does not link" "$(cat "$T/hello.err")"
fi
ld_fails nomain "$BOOT" "undefined symbol 'main'" "$T/rt_crt0.o" "$T/rt_isr_default.o"

# ===========================================================================
printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
