"""Run-time helpers for `*`, `/` and `%`, written in assembly.  The
compiler adds the ones a file uses to that file, as internal routines
with a static frame, so no run-time library is needed.  Names starting
with `__` are reserved for the toolchain (docs/y.md 4.2).

    __mul{w}       frame: +0 result, +n a, +2n b               (signed and unsigned)
    __divmodu{w}   frame: +0 a / b, +n a, +2n b, +3n a % b
    __divmods{w}   the same, signed: the quotient rounds toward 0, the
                   remainder has the sign of a; +4n, +4n+1: signs

n = w / 8 bytes.  `/` and `%` call the same routine and read the
quotient or the remainder.  For w = 32 the routines need r12 as their
loop counter, so they save the return address in their frame."""

from __future__ import annotations


def helper_name(op: str, bits: int, signed: bool) -> str:
    if op == "*":
        return "__mul%d" % bits
    return "__divmod%s%d" % ("s" if signed else "u", bits)


def result_offset(op: str, bits: int) -> int:
    """Where the routine of op leaves the result, in its frame."""
    return 3 * (bits // 8) if op == "%" else 0


class _Asm:
    def __init__(self, name: str) -> None:
        self.name = name
        self.lines: list[str] = []
        self.n = 0

    def ins(self, ins: str, ops: str = "", comment: str = "") -> None:
        text = "%-7s %s" % (ins, ops) if ops else ins
        self.lines.append("        %-30s ; %s" % (text, comment) if comment else "        " + text)

    def label(self, k: int, comment: str = "") -> str:
        lab = "%s.%d" % (self.name, k)
        self.lines.append("%s:%s" % (lab, " " * max(1, 39 - len(lab)) + "; " + comment if comment else ""))
        return lab

    def frame(self, off: int) -> str:
        return "=%s.frame%s" % (self.name, "+%d" % off if off else "")


def _seq(n: int, first: str, rest: str, last: str, single: str) -> list[str]:
    """The mnemonics of an n-byte chain, low byte first."""
    if n == 1:
        return [single]
    return [first] + [rest] * (n - 2) + [last]


def _chain(a: _Asm, mnemonics: list[str], ops: list[str], comment: str) -> None:
    for k, (ins, o) in enumerate(zip(mnemonics, ops)):
        a.ins(ins, o, comment if k == 0 else "")


def _negate(a: _Asm, regs: list[int], what: str) -> None:
    for k, r in enumerate(regs):
        a.ins("eor", "r%d, r%d, #255" % (r, r), "negate %s: invert ..." % what if k == 0 else "")
    _chain(a, _seq(len(regs), "adds", "addcs", "addc", "add"),
           ["r%d, r%d, #%d" % (r, r, 1 if k == 0 else 0) for k, r in enumerate(regs)], "... + 1")


def _layout(name: str, n: int, divmod: bool, signed: bool, save_lr: int | None) -> tuple[int, list[str]]:
    rows = [(0, n, "a / b" if divmod else "result"), (n, n, "a"), (2 * n, n, "b")]
    if divmod:
        rows.append((3 * n, n, "a % b"))
    if signed:
        rows += [(4 * n, 1, "the sign of a (bit 7)"), (4 * n + 1, 1, "the sign of a / b (bit 7)")]
    if save_lr is not None:
        rows.append((save_lr, 2, "saved return address (r12a)"))
    size = max(off + sz for off, sz, _ in rows)
    out = ["; frame of %s, %d bytes (a ylangc helper)" % (name, size)]
    out += [";   +%-4d %-3d %s" % row for row in rows]
    return size, out


def _routine(name: str, n: int, divmod: bool, signed: bool) -> tuple[list[str], int, list[str]]:
    a = _Asm(name)
    A = list(range(n))                       # a, then the quotient
    B = list(range(n, 2 * n))                # b
    P = list(range(2 * n, 3 * n))            # the product, or the remainder
    save = 3 * n + 1 > 12                    # r12 is the only register left for the counter
    cnt = "r12" if save else "r%d" % (3 * n)
    lr = (4 * n + 2 if signed else (4 * n if divmod else 3 * n)) if save else None
    a.lines += ["", "; " + "-" * 78,
                "; %s: %s, %s, %d bit (ylangc helper)" % (
                    name, "a / b and a % b" if divmod else "a * b", "signed" if signed else "unsigned", 8 * n),
                "; " + "-" * 78, "%s:" % name]
    if save:
        a.ins("str", "r12, %s" % a.frame(lr), "save the return address: r12 counts")
        a.ins("str", "r13, %s" % a.frame(lr + 1))
    for k in range(n):
        a.ins("ldr", "r%d, %s" % (A[k], a.frame(n + k)), "a" if k == 0 else "")
    for k in range(n):
        a.ins("ldr", "r%d, %s" % (B[k], a.frame(2 * n + k)), "b" if k == 0 else "")
    if signed:
        a.ins("str", "r%d, %s" % (A[-1], a.frame(4 * n)), "the sign of a: the sign of a % b")
        a.ins("eor", "r%d, r%d, r%d" % (P[0], A[-1], B[-1]), "the sign of a / b")
        a.ins("str", "r%d, %s" % (P[0], a.frame(4 * n + 1)))
        a.ins("andd", "r%d, #128" % A[-1], "a < 0?")
        a.ins("br.eq", "=%s.4" % name)
        _negate(a, A, "a")
        a.label(4)
        a.ins("andd", "r%d, #128" % B[-1], "b < 0?")
        a.ins("br.eq", "=%s.5" % name)
        _negate(a, B, "b")
        a.label(5)
    for k in range(n):
        a.ins("mov", "r%d, #0" % P[k], ("remainder" if divmod else "product") + " = 0" if k == 0 else "")
    a.ins("mov", "%s, #%d" % (cnt, 8 * n), "%d passes, one per bit" % (8 * n))
    if divmod:
        a.label(1, "loop: shift a into the remainder, subtract b if it fits")
        RA = A + P
        _chain(a, _seq(2 * n, "lsls", "csls", "csls", "lsls"), ["r%d, r%d" % (r, r) for r in RA],
               "remainder:a <<= 1, C = the bit out")
        a.ins("br.geu", "=%s.2" % name, "a bit fell out: the remainder is > b")
        _chain(a, _seq(n, "cmp", "subcd", "subcd", "cmp"), ["r%d, r%d" % (P[k], B[k]) for k in range(n)],
               "remainder - b")
        a.ins("br.su", "=%s.3" % name, "remainder < b: the quotient bit is 0")
        a.label(2)
        _chain(a, _seq(n, "subs", "subcs", "subc", "sub"), ["r%d, r%d, r%d" % (P[k], P[k], B[k]) for k in range(n)],
               "remainder -= b")
        a.ins("or", "r%d, r%d, #1" % (A[0], A[0]), "the quotient bit is 1")
        a.label(3)
    else:
        a.label(1, "loop: add a for every 1 bit of b")
        _chain(a, _seq(n, "lsrs", "csrs", "csrs", "lsrs"), ["r%d, r%d" % (r, r) for r in reversed(B)],
               "b >>= 1, C = its low bit")
        a.ins("br.su", "=%s.2" % name, "0: nothing to add")
        _chain(a, _seq(n, "adds", "addcs", "addc", "add"), ["r%d, r%d, r%d" % (P[k], P[k], A[k]) for k in range(n)],
               "product += a")
        a.label(2)
        _chain(a, _seq(n, "lsls", "csls", "csl", "lsl"), ["r%d, r%d" % (r, r) for r in A], "a <<= 1")
    a.ins("subs", "%s, %s, #1" % (cnt, cnt), "next pass")
    a.ins("br.ne", "=%s.1" % name)
    if signed:
        a.ins("ldr", "r%d, %s" % (B[0], a.frame(4 * n + 1)), "a / b < 0?")
        a.ins("andd", "r%d, #128" % B[0])
        a.ins("br.eq", "=%s.6" % name)
        _negate(a, A, "a / b")
        a.label(6)
        a.ins("ldr", "r%d, %s" % (B[0], a.frame(4 * n)), "a % b < 0?")
        a.ins("andd", "r%d, #128" % B[0])
        a.ins("br.eq", "=%s.7" % name)
        _negate(a, P, "a % b")
        a.label(7)
    if divmod:
        for k in range(n):
            a.ins("str", "r%d, %s" % (A[k], a.frame(k)), "a / b" if k == 0 else "")
        for k in range(n):
            a.ins("str", "r%d, %s" % (P[k], a.frame(3 * n + k)), "a % b" if k == 0 else "")
    else:
        for k in range(n):
            a.ins("str", "r%d, %s" % (P[k], a.frame(k)), "the product" if k == 0 else "")
    if save:
        a.ins("ldr", "r12, %s" % a.frame(lr), "reload the return address")
        a.ins("ldr", "r13, %s" % a.frame(lr + 1))
    a.ins("br", "r12a", "back to the caller")
    size, layout = _layout(name, n, divmod, signed, lr)
    return a.lines, size, layout


def routine(name: str) -> tuple[list[str], int, list[str]]:
    """The code lines, frame size and frame layout comment of a helper."""
    if name.startswith("__mul"):
        return _routine(name, int(name[5:]) // 8, False, False)
    signed = name[8] == "s"
    return _routine(name, int(name[9:]) // 8, True, signed)
