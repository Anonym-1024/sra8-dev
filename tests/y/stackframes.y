// Compiler test program for ABI 0.3: static and stack frames called through
// pointers (the header dispatch), struct results, a pointer to a local of a
// recursive function, a stack frame above 2 KiB (far offsets) and a field at
// offset 3000 behind a pointer. Expected out[0..8]: 42 55 705 303 909 55 15
// 0xBEEF 90. The stack of deepframe(3) needs about 8.5 KiB of RAM.

type point = struct{x: int16, y: int16};
type big = struct{pad: [3000]uint8, tail: uint16};

var out: [16]int32 = {0, _};
var bigone: big = undefined;

impl twice: fn(x: int16) returns int16 { return x + x; }
@recursive impl tri: fn(x: int16) returns int16 {
    if (x le 0) { return 0; }
    return x + tri(x - 1);
}
impl flip: fn(p: point) returns point { return {x = p.y, y = p.x}; }
@recursive impl rflip: fn(p: point, n: uint8) returns point {
    if (n eq 0) { return p; }
    return rflip({x = p.y, y = p.x + 1}, n - 1);
}

// a pointer to a local of a recursive function, passed down the recursion
@recursive impl sum_into: fn(n: uint8, acc: *uint16) {
    if (n eq 0) { return; }
    var local: uint16 = 0;
    sum_into(n - 1, @ptr(local));
    [acc] += local + @cast(uint16, n);
}

// a recursive function with a frame larger than 2 KiB: far offsets
@recursive impl deepframe: fn(n: uint8) returns uint16 {
    var buf: [2100]uint8 = {0, _};
    buf[2099] = n;
    buf[0] = n + 1;
    if (n eq 0) { return @cast(uint16, buf[2099]); }
    var r: uint16 = deepframe(n - 1);
    return r + @cast(uint16, buf[2099]) + @cast(uint16, buf[0]);
}

impl call_int: fn(f: *fn(x: int16) returns int16, v: int16) returns int16 { return f(v); }
impl call_pt: fn(f: *fn(p: point) returns point, p: point) returns point { return f(p); }
impl flip1: fn(p: point) returns point { return rflip(p, 1); }

@main
impl start: fn() {
    out[0] = @cast(int32, call_int(@ptr(twice), 21));        // static frame through a pointer
    out[1] = @cast(int32, call_int(@ptr(tri), 10));          // stack frame through a pointer
    var q: point = call_pt(@ptr(flip), {x = 5, y = 7});
    out[2] = @cast(int32, q.x) * 100 + @cast(int32, q.y);
    var r: point = rflip({x = 1, y = 2}, 3);
    out[3] = @cast(int32, r.x) * 100 + @cast(int32, r.y);
    var r2: point = call_pt(@ptr(flip1), {x = 8, y = 9});
    out[4] = @cast(int32, r2.x) * 100 + @cast(int32, r2.y);
    var total: uint16 = 0;
    sum_into(10, @ptr(total));
    out[5] = @cast(int32, total);
    out[6] = @cast(int32, deepframe(3));
    var p: *big = @ptr(bigone);
    [p].tail = 0xBEEF;
    [p].pad[2999] = 0x5A;
    out[7] = @cast(int32, [p].tail);
    out[8] = @cast(int32, bigone.pad[2999]);
}
