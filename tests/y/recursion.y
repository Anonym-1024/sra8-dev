// Compiler test program for recursion with ABI 0.3 stack frames: parameters
// swapped in the recursive call, struct arguments and results, locals alive
// across calls, a call back into the same function through a pointer, mutual
// recursion.

type point = struct{x: int16, y: int16};

var out: [16]int32 = {0, _};

@recursive impl swapper: fn(a: int16, b: int16, n: uint8) returns int16 {
    if (n eq 0) { return a * 10 + b; }
    return swapper(b, a, n - 1);
}

@recursive impl pswap: fn(p: point, q: point, n: uint8) returns point {
    if (n eq 0) { return {x = p.x * 10 + q.x, y = p.y * 10 + q.y}; }
    return pswap(q, p, n - 1);
}

// keeps locals alive across its own call
@recursive impl sumsq: fn(n: uint16) returns uint32 {
    if (n eq 0) { return 0; }
    var mine: uint32 = @cast(uint32)n * @cast(uint32)n;
    var rest: uint32 = sumsq(n - 1);
    return mine + rest;
}

@recursive decl through: fn(n: uint8) returns uint16;
var tp: *fn(n: uint8) returns uint16 = @ptr(through);

// calls itself through a pointer: it must be @recursive (nothing checks it)
@recursive impl through: fn(n: uint8) returns uint16 {
    if (n eq 0) { return 1; }
    var mine: uint16 = @cast(uint16)n;
    return mine + tp(n - 1) * 2;
}

@recursive decl ping: fn(n: uint8, acc: uint16) returns uint16;
@recursive impl pong: fn(n: uint8, acc: uint16) returns uint16 {
    var keep: uint16 = acc + 1;
    if (n eq 0) { return keep; }
    var r: uint16 = ping(n - 1, keep * 2);
    return r + keep;
}
@recursive impl ping: fn(n: uint8, acc: uint16) returns uint16 {
    var keep: uint16 = acc + 3;
    if (n eq 0) { return keep; }
    var r: uint16 = pong(n - 1, keep);
    return r - keep;
}

@recursive impl depth: fn(n: uint8, p: *uint8) {
    if (n eq 0) { return; }
    [p] += 1;
    depth(n - 1, p);
}

@main
impl start: fn() {
    out[0] = @cast(int32)swapper(1, 2, 3);
    out[1] = @cast(int32)swapper(1, 2, 4);
    var r: point = pswap({x = 1, y = 3}, {x = 2, y = 4}, 5);
    out[2] = @cast(int32)r.x;
    out[3] = @cast(int32)r.y;
    out[4] = @as(int32)sumsq(20);
    out[5] = @cast(int32)through(5);
    out[6] = @cast(int32)ping(7, 1);
    var cnt: uint8 = 0;
    depth(200, @ptr(cnt));
    out[7] = @cast(int32)cnt;
}
