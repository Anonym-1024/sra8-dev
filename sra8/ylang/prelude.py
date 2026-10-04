"""Run-time helpers for `*`, `/` and `%`, written in Y.  The compiler
compiles the ones a file uses into that file as internal functions, so
no run-time library is needed.  Names starting with `__` are reserved
for the toolchain (docs/y.md 4.2)."""

from __future__ import annotations

_TEMPLATE = """
internal impl __mul{w}: fn(a: uint{w}, b: uint{w}) returns uint{w} {{
    var r: uint{w} = 0;
    loop {{
        if (b eq 0) {{ break; }}
        if ((b & 1) ne 0) {{ r += a; }}
        a = a shl 1;
        b = b shr 1;
    }}
    return r;
}}

internal impl __divu{w}: fn(a: uint{w}, b: uint{w}) returns uint{w} {{
    var q: uint{w} = 0;
    var r: uint{w} = 0;
    var i: uint8 = {w};
    loop {{
        if (i eq 0) {{ break; }}
        r = (r shl 1) | (a shr {top});
        a = a shl 1;
        q = q shl 1;
        if (r ge b) {{
            r -= b;
            q |= 1;
        }}
        i -= 1;
    }}
    return q;
}}

internal impl __modu{w}: fn(a: uint{w}, b: uint{w}) returns uint{w} {{
    var r: uint{w} = 0;
    var i: uint8 = {w};
    loop {{
        if (i eq 0) {{ break; }}
        r = (r shl 1) | (a shr {top});
        a = a shl 1;
        if (r ge b) {{ r -= b; }}
        i -= 1;
    }}
    return r;
}}

internal impl __divs{w}: fn(a: int{w}, b: int{w}) returns int{w} {{
    var negative: bool = false;
    var ua: uint{w} = @cast(uint{w})a;
    var ub: uint{w} = @cast(uint{w})b;
    if (a lt 0) {{
        ua = @cast(uint{w})(-a);
        negative = ~negative;
    }}
    if (b lt 0) {{
        ub = @cast(uint{w})(-b);
        negative = ~negative;
    }}
    var q: int{w} = @cast(int{w})__divu{w}(ua, ub);
    if (negative) {{ return -q; }}
    return q;
}}

internal impl __mods{w}: fn(a: int{w}, b: int{w}) returns int{w} {{
    var ua: uint{w} = @cast(uint{w})a;
    var ub: uint{w} = @cast(uint{w})b;
    if (a lt 0) {{ ua = @cast(uint{w})(-a); }}
    if (b lt 0) {{ ub = @cast(uint{w})(-b); }}
    var r: int{w} = @cast(int{w})__modu{w}(ua, ub);
    if (a lt 0) {{ return -r; }}
    return r;
}}
"""


def source() -> str:
    return "".join(_TEMPLATE.format(w=w, top=w - 1) for w in (8, 16, 32))


def helper_name(op: str, bits: int, signed: bool) -> str:
    if op == "*":
        return "__mul%d" % bits
    kind = {"/": "div", "%": "mod"}[op]
    return "__%s%s%d" % (kind, "s" if signed else "u", bits)
