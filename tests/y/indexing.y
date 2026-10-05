// Compiler test program for indexing and pointer access (ylangc 0.4: index
// registers, pointer variables loaded straight into r10a, 2-D arrays, arrays
// behind pointers, struct elements, negative indices, a static array over
// 2 KiB, locals of a @recursive function). The results in out[0..29] were
// checked against ylangc 0.3 and on the RTL.

// index / pointer access patterns: every result goes to out[]
type pt = struct{x: int16, y: int8, tag: [3]uint8};
type grid = struct{w: uint8, cells: [4][5]int16};

var out: [64]int32 = {0, _};
var g8: [10]int8 = {1, -2, 3, -4, 5, -6, 7, -8, 9, -10};
var g16: [6]uint16 = {100, 200, 300, 400, 500, 60000};
var g32: [4]int32 = {-100000, 7, 123456789, -5};
var pts: [4]pt = {{x = 1, y = 2, tag = {3, 4, 5}}, {x = -6, y = 7, tag = {8, 9, 10}},
                  {x = 11, y = -12, tag = {13, 14, 15}}, {x = 16, y = 17, tag = {18, 19, 20}}};
var gr: grid = {w = 5, cells = {{1, 2, 3, 4, 5}, {6, 7, 8, 9, 10}, {11, 12, 13, 14, 15}, {16, 17, 18, 19, 20}}};
var big: [3000]uint8 = undefined;
var k: uint8 = 0;

impl put: fn(v: int32) { out[k] = v; k += 1; }

impl sum8: fn(p: [*]int8, n: uint8) returns int16 {
    var s: int16 = 0;
    var i: uint8 = 0;
    loop { if (i eq n) { break; } s += @cast(int16)p[i]; i += 1; }
    return s;
}

impl rev16: fn(p: [*]uint16, n: int8) {
    var i: int8 = 0;
    var j: int8 = n - 1;
    loop {
        if (i ge j) { break; }
        var t: uint16 = p[i];
        p[i] = p[j];
        p[j] = t;
        i += 1;
        j -= 1;
    }
}

impl ptsum: fn(p: [*]pt, n: uint16) returns int32 {
    var s: int32 = 0;
    var i: uint16 = 0;
    loop {
        if (i eq n) { break; }
        s += @cast(int32)p[i].x * 1000 + @cast(int32)p[i].y + @cast(int32)p[i].tag[2] * 100000;
        p[i].tag[1] += 1;
        i += 1;
    }
    return s;
}

@recursive impl rlocal: fn(n: uint8) returns int32 {
    var a: [7]int16 = {0, _};
    var i: uint8 = 0;
    loop { if (i eq 7) { break; } a[i] = @cast(int16)i * @cast(int16)n - 3; i += 1; }
    var s: int32 = 0;
    if (n ne 0) { s = rlocal(n - 1); }
    var j: int8 = 6;
    loop { if (j lt 0) { break; } s = s * 3 + @cast(int32)a[j]; j -= 1; }
    var q: [*]int16 = @ptr(a[2]);
    s += @cast(int32)q[1] + @cast(int32)q[-2];
    return s;
}

impl idx: fn(i: uint8) returns uint8 { return i; }

@main
impl main: fn() {
    var i: uint8 = 0;
    var loc: [8]int32 = {5, -7, 9, -11, 13, -15, 17, -19};
    loop {
        if (i eq 8) { break; }
        put(loc[i] + @cast(int32)g8[i] * @cast(int32)g16[i % 6]);
        i += 1;
    }
    put(@cast(int32)sum8(@ptr(g8), 10));
    put(@cast(int32)sum8(@ptr(g8[3]), 5));
    rev16(@ptr(g16), 6);
    var j: int16 = 0;
    loop { if (j eq 6) { break; } put(@cast(int32)g16[j]); j += 1; }
    put(ptsum(@ptr(pts), 4));
    put(@cast(int32)pts[2].tag[1]);
    var r: uint8 = 0;
    loop {
        if (r eq 4) { break; }
        var c: uint8 = 0;
        loop { if (c eq 5) { break; } gr.cells[r][c] = gr.cells[r][c] * @cast(int16)(r + 1) - @cast(int16)c; c += 1; }
        r += 1;
    }
    put(@cast(int32)gr.cells[3][4] + @cast(int32)gr.cells[1][2] * 100);
    var pg: *grid = @ptr(gr);
    var m: uint8 = 2;
    put(@cast(int32)[pg].cells[m][m + 1]);
    [pg].cells[m][idx(1)] = 999;
    put(@cast(int32)gr.cells[2][1]);
    var bi: uint16 = 2999;
    big[bi] = 77;
    big[bi - 2999] = 66;
    put(@cast(int32)big[2999] * 1000 + @cast(int32)big[0]);
    var pb: [*]uint8 = @ptr(big[1000]);
    pb[bi - 1000] += 1;
    put(@cast(int32)big[2999]);
    put(rlocal(3));
    var s: int8 = -3;
    var p8: [*]int8 = @ptr(g8[5]);
    put(@cast(int32)p8[s] * 10 + @cast(int32)p8[s + 4]);
    p8[idx(1)] = p8[idx(2)] + p8[s];
    put(@cast(int32)g8[6]);
    var pp: *pt = @ptr(pts[idx(3)]);
    put(@cast(int32)[pp].x + @cast(int32)[pp].tag[idx(0)]);
    var cp: pt = pts[i - 7];
    put(@cast(int32)cp.x * 100 + @cast(int32)cp.tag[2]);
    pts[idx(0)] = pts[3];
    put(@cast(int32)pts[0].x + @cast(int32)pts[0].tag[0]);
    put(@cast(int32)g32[idx(2)] - g32[@cast(uint8)g8[0] + 2]);
}
