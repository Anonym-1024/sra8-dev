/*
    A tour of the Y language (docs/y.md): every construct once.
    There is no compiler yet; this file is a syntax reference and the test
    input of the editor grammars.
*/

!IFNDEF TOUR_Y
!DEFINE TOUR_Y
!DEFINE LINE_LENGTH 32
!ENDIF

!IFDEF DEBUG
!DEFINE LEVEL 2
!ELSE IFNDEF QUIET
!DEFINE LEVEL 1
!ELSE
!DEFINE LEVEL 0
!ENDIF

// imports and forward declarations
decl uart_putc: fn(c: char);
decl uart_getc: fn() returns char;
decl ticks: uint32;
decl database: type;

// types
type point = struct{x: int16, y: int16};
type node = struct{value: int8, next: *node};
type handle = *database;
type word = union{value: uint16, bytes: [2]uint8};
type handler = fn(c: char);
type line = struct{
    text: [!LINE_LENGTH]char,
    length: uint8,
};

// global variables
var origin: point = {x = 0, y = 0};
var table: [8]uint8 = {1, 2, 4, _};
var matrix: [2][3]int8 = {{1, 2, 3}, {4, 5, 6}};
var greeting: [_]char = "Hello.\r\n";
var banner: *[7]char = s"ready\n";
var cursor: [*]char = s"Hello.";
var anything: *opaque = nullptr;
var on_key: *handler = @ptr(uart_putc);
internal var scratch: [256]uint8 = undefined;
internal var current: line = {text = {0, _}, length = 0};
internal var flag: bool = false;

impl manhattan: fn(a: *point, b: *point) returns int16 {
    var dx: int16 = [a].x - [b].x;
    var dy: int16 = [a].y - [b].y;
    if (dx lt 0) {
        dx = -dx;
    }
    if (dy lt 0) {
        dy = -dy;
    }
    return dx + dy;
}

internal impl append: fn(l: *line, c: char) returns bool {
    if ([l].length ge !LINE_LENGTH - 1) {
        return false;
    }
    [l].text[[l].length] = c;
    [l].length += 1;
    [l].text[[l].length] = 0;
    return true;
}

impl print: fn(s: [*]char) {
    var i: uint16 = 0;
    loop {
        if (s[i] eq 0) {
            break;
        }
        uart_putc(s[i]);
        i += 1;
    }
}

impl arithmetic: fn(a: int8, b: uint16, w: word) returns uint16 {
    var x: uint16 = @cast(uint16)a + b * 3 / 2 % 7;
    x = x & 0x0F | 0b1010 ^ 0o17;
    x = ~x shl 2 shr 1;
    x = x rol 4 ror 0d3;
    var s: int8 = a sar 1;
    var n: uint8 = @sizeof(point) * 4 + 1;
    var big: int32 = @cast(int32)s;
    var bits: uint16 = @as(uint16)w;
    var low: uint8 = w.bytes[0];
    var same: bool = @bool(a eq 0 and not (b ne 0 or x gt 3));
    var c: char = 'a';
    var nl: char = '\n';
    if (same) {
        x -= 1;
    } else if (b le 100) {
        x *= 2;
    } else {
        x /= 2;
    }
    _ = big;
    return x + @cast(uint16)n + @cast(uint16)low + @cast(uint16)c + @cast(uint16)nl + bits;
}

impl pointers: fn(p: *[4]int8, many: [*]int8, f: *fn(c: char)) {
    var first: int8 = [p][0];
    var second: *int8 = p + 1;
    var third: int8 = [many + 2];
    var any: *opaque = p;
    var back: *int8 = @as(*int8)any;
    var where: addr = back;
    var distance: addr = where - p;
    many[3] = first + [second] + third + @cast(int8)distance;
    if (any ne nullptr and where gt 0x1000) {
        f('x');
    }
}

impl search: fn(rows: *[2][3]int8, wanted: int8) returns bool {
    var r: uint8 = 0;
    loop rows_loop {
        if (r ge 2) {
            break;
        }
        var c: uint8 = 0;
        loop {
            if (c ge 3) {
                break;
            }
            if ([rows][r][c] eq wanted) {
                return true;
            }
            c += 1;
            continue;
        }
        r += 1;
        continue rows_loop;
    }
    return false;
}

@section(isr)
impl handler_entry: fn() {
    @reg var count: uint8 = 0;
    flag = true;
    count += 1;
}

@main
impl echo: fn() {
    print(s"ready\r\n");
    loop {
        var c: char = uart_getc();
        if (c eq '\r' or not append(@ptr(current), c)) {
            print(@ptr(current.text));
            current.length = 0;
            continue;
        }
        uart_putc(c);
    }
}
