// Compiler test program: the checks store into out[k]. Checked by running it on
// the RTL and an instruction simulator while ylangc 0.1 was written; the test
// suite only compiles, assembles and links it.

type point = struct{x: int16, y: int16};
type node = struct{value: int8, next: *node};
type word = union{value: uint16, bytes: [2]uint8};
type line = struct{text: [8]char, length: uint8};

var out: [64]int32 = {0, _};
var n_out: uint8 = 0;

var table: [8]uint8 = {1, 2, 4, _};
var matrix: [2][3]int8 = {{1, 2, 3}, {4, 5, 6}};
var greeting: [_]char = "Hey";
var banner: *[5]char = s"abcd";
var cursor: [*]char = s"xyz";
var origin: point = {y = -7, x = 300};
var nodes: [3]node = {{value = 1, next = nullptr}, {value = 2, next = nullptr}, {value = 3, next = nullptr}};
var pnode: *node = @ptr(nodes[1]);
var scratch: [16]uint8 = undefined;
var flag: bool = true;

decl odd: fn(n: uint8) returns bool;

impl put: fn(v: int32) {
    out[n_out] = v;
    n_out += 1;
}

impl even: fn(n: uint8) returns bool {
    if (n eq 0) { return true; }
    return odd(n - 1);
}

impl odd: fn(n: uint8) returns bool {
    if (n eq 0) { return false; }
    return even(n - 1);
}

impl fact: fn(n: uint16) returns uint32 {
    if (n le 1) { return 1; }
    return @cast(uint32)n * fact(n - 1);
}

impl fib: fn(n: int16) returns int16 {
    if (n lt 2) { return n; }
    return fib(n - 1) + fib(n - 2);
}

impl swap: fn(p: point) returns point {
    return {x = p.y, y = p.x};
}

impl sum_array: fn(a: [8]uint8) returns uint16 {
    var s: uint16 = 0;
    var i: uint8 = 0;
    loop {
        if (i ge 8) { break; }
        s += @cast(uint16)a[i];
        i += 1;
    }
    return s;
}

impl strlen: fn(s: [*]char) returns uint16 {
    var n: uint16 = 0;
    loop {
        if (s[n] eq 0) { break; }
        n += 1;
    }
    return n;
}

impl twice: fn(x: int16) returns int16 { return x + x; }
impl thrice: fn(x: int16) returns int16 { return x * 3; }

impl apply: fn(f: *fn(x: int16) returns int16, v: int16) returns int16 {
    return f(v);
}

impl append: fn(l: *line, c: char) returns bool {
    if ([l].length ge 7) { return false; }
    [l].text[[l].length] = c;
    [l].length += 1;
    [l].text[[l].length] = 0;
    return true;
}

impl deep: fn(a: int32, b: int32, c: int32, d: int32) returns int32 {
    // more temps than registers: forces spills
    return ((a + b) * (c - d)) + ((a ^ c) | (b & d)) - ((a + c) - (b + d)) + (a shl 3) + (d sar 2);
}

@main
impl start: fn() {
    // 0..3 recursion
    put(@cast(int32)@cast(uint8)@bool(even(10)));
    put(@cast(int32)@cast(uint8)@bool(odd(7)));
    put(@as(int32)fact(10));
    put(@cast(int32)fib(15));

    // 4..7 structs and unions
    var p: point = swap(origin);
    put(@cast(int32)p.x);
    put(@cast(int32)p.y);
    var w: word = {value = 0x1234};
    put(@cast(int32)w.bytes[0]);
    put(@cast(int32)w.bytes[1]);

    // 8..11 arrays
    put(@cast(int32)sum_array(table));
    put(@cast(int32)matrix[1][2]);
    var i: uint8 = 1;
    var j: int16 = 2;
    put(@cast(int32)matrix[i][j]);
    put(@cast(int32)table[i + 4]);

    // 12..15 strings and pointers
    put(@cast(int32)strlen(@ptr(greeting)));
    put(@cast(int32)strlen(banner));
    put(@cast(int32)cursor[2]);
    put(@cast(int32)[banner][3]);

    // 16..19 linked list, pointer walking
    nodes[0].next = @ptr(nodes[1]);
    nodes[1].next = @ptr(nodes[2]);
    var total: int8 = 0;
    var q: *node = @ptr(nodes[0]);
    loop {
        if (q eq nullptr) { break; }
        total += [q].value;
        q = [q].next;
    }
    put(@cast(int32)total);
    put(@cast(int32)[pnode].value);
    var many: [*]uint8 = @ptr(table);
    many = @ptr(many[2]);
    put(@cast(int32)many[0]);
    put(@cast(int32)many[1]);

    // 20..23 function pointers, logic
    put(@cast(int32)apply(@ptr(twice), 21));
    put(@cast(int32)apply(@ptr(thrice), -5));
    var k: uint8 = 5;
    put(@cast(int32)@cast(uint8)@bool(k gt 3 and not (k eq 4) or flag and k lt 0));
    put(@cast(int32)@cast(uint8)@bool(not flag or k ne 5));

    // 24..27 nested loops with names
    var count: int32 = 0;
    var a: uint8 = 0;
    loop outer {
        a += 1;
        if (a gt 5) { break; }
        var b: uint8 = 0;
        loop {
            b += 1;
            if (b gt 4) { continue outer; }
            if (a eq 3 and b eq 2) { continue; }
            if (a eq 5 and b eq 3) { break outer; }
            count += 1;
        }
    }
    put(count);
    put(deep(1000, -77, 123456, 9));
    var ln: line = {text = {0, _}, length = 0};
    _ = append(@ptr(ln), 'h');
    _ = append(@ptr(ln), 'i');
    put(@cast(int32)ln.text[1]);
    put(@cast(int32)strlen(@ptr(ln.text)));

    // 28..31 casts, @as, addr, compound ops
    var neg: int8 = -3;
    put(@cast(int32)neg);
    put(@cast(int32)@cast(uint8)neg);
    var where: addr = @ptr(table);
    var start_: addr = @ptr(table[3]);
    put(@cast(int32)(start_ - where));
    var acc: int16 = 100;
    acc -= 30;
    acc *= -2;
    acc /= 7;
    acc %= 6;
    put(@cast(int32)acc);

    // 32..35 array copies, fill, assignment of aggregates
    var copy: [8]uint8 = table;
    copy[0] = 99;
    put(@cast(int32)table[0]);
    put(@cast(int32)copy[0] + @cast(int32)copy[7]);
    var pts: [3]point = {{x = 1, y = 2}, {x = 3, y = 4}, _};
    put(@cast(int32)pts[2].x * 10 + @cast(int32)pts[2].y);
    pts[0] = pts[1];
    put(@cast(int32)pts[0].y);
}
