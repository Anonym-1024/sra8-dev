"""Type checker and code generator of ylangc 0.3.

Deliberately simple (docs/ylangc.md):

* A function has a static frame, `name.frame`, in .bss, unless it is
  @recursive: then its frame is on the stack.  Static frame bytes are reached
  with `ldr r0, =f.frame+k`, stack frame bytes with `ldo r0, r14a, #k`; both
  are one instruction.
* Every variable lives in memory.  Nothing is kept in a register across
  statements.
* While an expression is computed, intermediate values ("temps") stay in
  r0 ... r9.  When those run out, the oldest temp is written to a spill
  slot in the frame and loaded again when it is needed.
* Before every call and every branch inside an expression, all temps are
  written to their spill slots, so every label is reached with nothing in
  registers.

ABI 0.3 (docs/ylangc.md): arguments of a non-recursive function go into its
static frame; arguments of a @recursive function go onto the stack below
SP.  Every function starts with a header that tells calls through a
pointer which of the two it is.  Every register may be changed by a call.
Whether a non-recursive function is re-entered is not checked.
"""

from __future__ import annotations

import re

from . import VERSION
from .ast import Node
from .errors import YError
from . import prelude
from .types import (BOOL, COND, INT16, NULL, UINT8, UINT16, ArrayT, BoolT, FnT, IntT, ManyT, NamedT,
                    NullT, PtrT, StructT, Type, BUILTIN_TYPES, implicit, is_aggregate, is_int, is_ptr, same)


class VoidT(Type):
    complete = False

    def __str__(self) -> str:
        return "nothing"


VOID = VoidT()
REGS = list(range(10))              # r0 ... r9 hold temps
# instructions that write no general register named in their operands
READ_ONLY = {"str", "sto", "cmp", "cmn", "ord", "andd", "eord", "subcd", "addcd", "ptw", "br", "brl",
             "lsld", "lsrd"}


class Sym:
    """A name: kind is 'var', 'func' or 'type'."""

    def __init__(self, kind: str, name: str, ty: Type, where: tuple[str, int]) -> None:
        self.kind = kind
        self.name = name
        self.ty = ty
        self.where = where
        self.defined = False
        self.internal = False
        self.declared = False         # by decl
        self.used = False
        self.loc = None               # GlobalLoc of a variable
        self.helper = False
        self.recursive = False        # functions: @recursive
        self.called = False           # functions: called directly (its frame is used)
        self.addressed = False        # functions: @ptr taken in this file (needs its header)


# ---------------------------------------------------------------------------------------------
# locations and temps (code generation)
# ---------------------------------------------------------------------------------------------

class GlobalLoc:
    """Memory at a label: a global variable, a string, or a byte of a frame."""

    def __init__(self, label: str, off: int = 0, desc: str = "") -> None:
        self.label, self.off, self.desc = label, off, desc or label

    def plus(self, n: int, desc: str | None = None) -> "GlobalLoc":
        return GlobalLoc(self.label, self.off + n, desc or ("%s+%d" % (self.desc, n) if n else self.desc))

    def operand(self, k: int = 0) -> str:
        off = self.off + k
        return "=%s%s" % (self.label, "+%d" % off if off else "")


class Slot:
    """Part of the stack frame of a @recursive function.  kind: 'local'
    (offset fixed when allocated), 'lr' (the saved r12a, above the locals) or
    'caller' (the caller's result and argument area, above the frame)."""

    def __init__(self, size: int, kind: str, off: int, desc: str) -> None:
        self.size, self.kind, self.off, self.desc = size, kind, off, desc


class StackLoc:
    """Bytes of the stack frame of a @recursive function."""

    def __init__(self, slot: Slot, off: int = 0, desc: str = "") -> None:
        self.slot, self.off, self.desc = slot, off, desc or slot.desc

    def plus(self, n: int, desc: str | None = None) -> "StackLoc":
        return StackLoc(self.slot, self.off + n, desc or ("%s+%d" % (self.desc, n) if n else self.desc))


class SpLoc:
    """The argument area of a call to a @recursive function: byte off above
    SP as it was when the stack depth of the caller was delta."""

    def __init__(self, off: int, delta: int, desc: str = "") -> None:
        self.off, self.delta, self.desc = off, delta, desc

    def plus(self, n: int, desc: str | None = None) -> "SpLoc":
        return SpLoc(self.off + n, self.delta, desc or ("%s+%d" % (self.desc, n) if n else self.desc))


def fits12(v: int) -> bool:
    return -2048 <= v <= 2047


class PtrLoc:
    """Memory at an address computed into r10a when it is accessed:
    base + index + off.  The base is the address held by a temp, or
    base = ("mem", loc): the pointer stored in a GlobalLoc (loaded straight
    into r10a), or ("addr", loc): the address of loc (an array).  index is
    an optional 2-byte temp, already scaled by the element size."""

    def __init__(self, temp: "Temp | None", off: int = 0, desc: str = "", index: "Temp | None" = None,
                 base: tuple | None = None) -> None:
        self.temp, self.off, self.index, self.base = temp, off, index, base
        self.desc = desc or "[%s]" % (temp.desc if temp is not None else base[1].desc)

    def plus(self, n: int, desc: str | None = None) -> "PtrLoc":
        return PtrLoc(self.temp, self.off + n, desc or ("%s+%d" % (self.desc, n) if n else self.desc),
                      self.index, self.base)

    def temps(self) -> list:
        return [t for t in (self.temp, self.index) if t is not None]


class Temp:
    def __init__(self, size: int, desc: str = "") -> None:
        self.size = size
        self.desc = desc
        self.regs: list[int] | None = None
        self.slot: GlobalLoc | None = None
        self.pinned = 0
        self.dead = False
        self.const_bytes: list[int] | None = None  # a constant, while its registers are unchanged

    def r(self, k: int) -> str:
        assert self.regs is not None, "temp not in registers"
        return "r%d" % self.regs[k]

    def regs_text(self) -> str:
        return ":".join("r%d" % r for r in reversed(self.regs or []))


def byte_desc(desc: str, k: int, size: int) -> str:
    return desc if size == 1 else "%s (byte %d)" % (desc, k)


def lo(v: int) -> int:
    return v & 0xFF


def hi(v: int) -> int:
    return (v >> 8) & 0xFF


def le_bytes(value: int, size: int) -> list[int]:
    v = value & ((1 << (8 * size)) - 1)
    return [(v >> (8 * k)) & 0xFF for k in range(size)]


# ---------------------------------------------------------------------------------------------
# the compiler of one file
# ---------------------------------------------------------------------------------------------

class Module:
    def __init__(self, lines: list[tuple[str, int, str]]) -> None:
        self.scopes: list[dict[str, Sym]] = [{}]
        self.texts = {(f, n): t for f, n, t in lines}
        self.code_sections: list[tuple[str | None, list[str]]] = []
        self.data: list[str] = []
        self.bss: list[str] = []
        self.strings: list[tuple[str, list[int]]] = []
        self.main: Sym | None = None
        self.helpers_used: set[str] = set()
        self.fn: FuncGen | None = None
        self.frames: list[tuple[str, int, bool]] = []               # (label, size, exported)

    # -- names --------------------------------------------------------------------------------

    def lookup(self, name: str, where: tuple[str, int]) -> Sym:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise YError("'%s' is not declared" % name, where)

    def find(self, name: str) -> Sym | None:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def declare(self, sym: Sym) -> None:
        old = self.find(sym.name)
        if old is not None:
            raise YError("'%s' is already declared (at %s:%d); Y has no shadowing"
                         % (sym.name, old.where[0], old.where[1]), sym.where)
        self.scopes[-1][sym.name] = sym

    # -- types ----------------------------------------------------------------------------------

    def resolve(self, t: Node, infer_len: int | None = None) -> Type:
        k = t.kind
        if k == "tname":
            if t.name in BUILTIN_TYPES:
                return BUILTIN_TYPES[t.name]
            sym = self.lookup(t.name, t.where)
            if sym.kind != "type":
                raise YError("'%s' is not a type" % t.name, t.where)
            return sym.ty
        if k == "tptr":
            return PtrT(self.resolve(t.target))
        if k == "tmany":
            return ManyT(self.resolve(t.target))
        if k == "tarray":
            elem = self.resolve(t.elem)
            if not elem.resolved().complete or isinstance(elem.resolved(), FnT):
                raise YError("array elements must have a complete type, not %s" % elem, t.where)
            if t.length is None:
                if infer_len is None:
                    raise YError("'[_]' is only allowed for a variable with an initialiser", t.where)
                return ArrayT(infer_len, elem)
            n = self.const_int(t.length)
            if n < 1:
                raise YError("an array needs at least one element", t.where)
            return ArrayT(n, elem)
        if k == "tstruct":
            fields = []
            for name, ft, fw in t.fields:
                ty = self.resolve(ft)
                if not ty.resolved().complete:
                    raise YError("field '%s' has the incomplete type %s" % (name, ty), fw)
                if any(name == n for n, _ in fields):
                    raise YError("field '%s' twice" % name, fw)
                fields.append((name, ty))
            return StructT(fields, t.union)
        if k == "tfn":
            params = [self.resolve(p) for _, p in t.params]
            ret = self.resolve(t.ret) if t.ret else None
            return FnT(params, ret, [n for n, _ in t.params])
        raise AssertionError(k)

    def const_int(self, e: Node) -> int:
        self.check(e)
        if e.const is None or not (e.ty is None or is_int(e.ty)):
            raise YError("expected a constant integer expression", e.where)
        return e.const

    # -- checking (docs/y.md 8, 11) ----------------------------------------------------------------

    def check(self, e: Node, expected: Type | None = None) -> Type | None:
        """Type e, fold constants.  Returns None for a constant without a type."""
        ty = getattr(self, "check_" + e.kind)(e, expected)
        e.ty = ty
        return ty

    def check_int(self, e: Node, expected: Type | None) -> Type | None:
        e.const = e.value
        return None

    def check_true(self, e: Node, expected: Type | None) -> Type:
        e.const = 1
        return BOOL

    def check_false(self, e: Node, expected: Type | None) -> Type:
        e.const = 0
        return BOOL

    def check_nullptr(self, e: Node, expected: Type | None) -> Type:
        e.const = 0
        return NULL

    def check_str(self, e: Node, expected: Type | None) -> Type:
        return ArrayT(len(e.data) + 1, UINT8)

    def check_sstr(self, e: Node, expected: Type | None) -> Type:
        return PtrT(ArrayT(len(e.data) + 1, UINT8))

    def check_name(self, e: Node, expected: Type | None) -> Type:
        sym = self.lookup(e.name, e.where)
        if sym.kind == "type":
            raise YError("'%s' is a type, not a value" % e.name, e.where)
        sym.used = True
        e.sym = sym
        return sym.ty

    def check_sizeof(self, e: Node, expected: Type | None) -> Type | None:
        t = self.resolve(e.type)
        if not t.resolved().complete:
            raise YError("@sizeof of the incomplete type %s" % t, e.where)
        e.const = t.resolved().size
        return None

    def check_unary(self, e: Node, expected: Type | None) -> Type | None:
        if e.op == "not":
            self.cond(e.operand)
            if e.operand.const is not None:
                e.const = 1 - e.operand.const
            return COND
        t = self.check(e.operand, expected if is_int(expected) else None)
        if e.op == "~" and t is not None and isinstance(t.resolved(), BoolT):
            if e.operand.const is not None:
                e.const = 1 - e.operand.const
            return BOOL
        if t is None:                          # constant without a type
            if e.op == "-":
                e.const = -e.operand.const
                return None
            if not is_int(expected):
                raise YError("'~' of a constant needs a type: the context gives none", e.where)
            self.coerce(e.operand, expected)
            t = expected
        if not is_int(t):
            raise YError("'%s' needs an integer, not %s" % (e.op, t), e.where)
        if e.operand.const is not None:
            e.const = wrap(-e.operand.const if e.op == "-" else ~e.operand.const, t)
        return t

    def check_binary(self, e: Node, expected: Type | None) -> Type | None:
        op = e.op
        if op in ("and", "or"):
            self.cond(e.left)
            self.cond(e.right)
            a, b = e.left.const, e.right.const
            if a is not None and b is not None:
                e.const = int(bool(a and b)) if op == "and" else int(bool(a or b))
            return COND
        if op in ("eq", "ne", "lt", "le", "gt", "ge"):
            return self.check_compare(e)
        if op in ("shl", "shr", "sar", "rol", "ror"):
            return self.check_shift(e, expected)
        exp = expected if is_int(expected) else None
        lt = self.check(e.left, exp)
        if lt is not None and isinstance(lt.resolved(), (PtrT, ManyT, NullT)):
            raise YError("a pointer cannot be the left operand of '%s': pointers have no arithmetic "
                         "(index a [*]T instead)" % op, e.where)
        rt = self.check(e.right, lt if lt is not None else exp)
        if lt is None and rt is not None:
            self.coerce(e.left, rt)
            lt = rt
        if lt is None and rt is None:                 # a constant expression
            e.const = fold(op, e.left.const, e.right.const, e.where)
            return None
        if rt is None:
            self.coerce(e.right, lt)
            rt = lt
        self.value(e.left)
        self.value(e.right)
        L, R = lt.resolved(), rt.resolved()
        if isinstance(L, (PtrT, ManyT, NullT)):
            raise YError("a pointer cannot be the left operand of '%s': pointers have no arithmetic "
                         "(index a [*]T instead)" % op, e.where)
        if L is UINT16 and is_ptr(R) and op in ("+", "-", "*", "/", "%", "&", "|", "^"):
            e.right.conv = UINT16
            return UINT16
        if op in ("&", "|", "^") and isinstance(L, BoolT) and isinstance(R, BoolT):
            return BOOL
        if not (isinstance(L, IntT) and isinstance(R, IntT)):
            raise YError("'%s' needs two integers, not %s and %s" % (op, lt, rt), e.where)
        if L is not R:
            raise YError("'%s' of %s and %s: the types differ; convert one with @cast" % (op, lt, rt), e.where)
        if e.left.const is not None and e.right.const is not None:
            e.const = fold(op, e.left.const, e.right.const, e.where)
        return lt

    def check_shift(self, e: Node, expected: Type | None) -> Type | None:
        lt = self.check(e.left, expected if is_int(expected) else None)
        rt = self.check(e.right)
        if rt is None:
            self.coerce(e.right, UINT8)
            rt = UINT8
        if not (is_int(rt) and not rt.resolved().signed):
            raise YError("a shift count must be an unsigned integer, not %s" % rt, e.right.where)
        if lt is None:
            if e.op in ("rol", "ror") or e.right.const is None:
                if not is_int(expected):
                    raise YError("the constant shifted by '%s' needs a type; the context gives none" % e.op,
                                 e.where)
                self.coerce(e.left, expected)
                lt = expected
            else:
                e.const = fold(e.op, e.left.const, e.right.const, e.where)
                return None
        if not is_int(lt):
            raise YError("'%s' needs an integer on the left, not %s" % (e.op, lt), e.where)
        if e.left.const is not None and e.right.const is not None:
            e.const = fold_shift(e.op, e.left.const, e.right.const, lt.resolved())
        return lt

    def check_compare(self, e: Node) -> Type:
        lt = self.check(e.left)
        rt = self.check(e.right, lt)
        if lt is None and rt is not None:
            self.coerce(e.left, rt)
            lt = rt
        if lt is None and rt is None:
            a, b = e.left.const, e.right.const
            e.const = int({"eq": a == b, "ne": a != b, "lt": a < b, "le": a <= b,
                           "gt": a > b, "ge": a >= b}[e.op])
            e.cmp_ty = None
            return COND
        if rt is None:
            self.coerce(e.right, lt)
            rt = lt
        self.value(e.left)
        self.value(e.right)
        L, R = lt.resolved(), rt.resolved()
        if same(L, R):
            common = lt
        elif is_ptr(L) and is_ptr(R):
            if implicit(R, L):
                common = lt
            elif implicit(L, R):
                common = rt
            else:
                raise YError("cannot compare %s with %s" % (lt, rt), e.where)
        elif L is UINT16 and is_ptr(R) or R is UINT16 and is_ptr(L):
            common = UINT16
        else:
            raise YError("cannot compare %s with %s" % (lt, rt), e.where)
        c = common.resolved()
        if isinstance(c, BoolT) and e.op not in ("eq", "ne"):
            raise YError("bool values can only be compared with eq and ne", e.where)
        if not isinstance(c, (IntT, BoolT, PtrT, ManyT, NullT)):
            raise YError("values of type %s cannot be compared" % common, e.where)
        e.cmp_ty = common
        if e.left.const is not None and e.right.const is not None:
            a, b = e.left.const, e.right.const
            e.const = int({"eq": a == b, "ne": a != b, "lt": a < b, "le": a <= b,
                           "gt": a > b, "ge": a >= b}[e.op])
        return COND

    def check_call(self, e: Node, expected: Type | None) -> Type:
        f = e.func
        if f.kind == "name" and self.lookup(f.name, f.where).kind == "func":
            sym = self.lookup(f.name, f.where)
            sym.used = True
            f.sym = sym
            f.ty = sym.ty
            fnty = sym.ty
            e.direct = sym
        else:
            ft = self.check(f)
            if ft is None or not (isinstance(ft.resolved(), PtrT) and isinstance(ft.resolved().target.resolved(), FnT)):
                raise YError("only functions and function pointers can be called", e.where)
            fnty = ft.resolved().target.resolved()
            e.direct = None
        if len(e.args) != len(fnty.params):
            raise YError("%d arguments given, %d expected" % (len(e.args), len(fnty.params)), e.where)
        for a, p in zip(e.args, fnty.params):
            if not p.resolved().complete:
                raise YError("a parameter of the incomplete type %s" % p, a.where)
            self.coerce(a, p)
        e.fnty = fnty
        if fnty.ret is not None and not fnty.ret.resolved().complete:
            raise YError("the result type %s is incomplete" % fnty.ret, e.where)
        return fnty.ret if fnty.ret is not None else VOID

    def check_index(self, e: Node, expected: Type | None) -> Type:
        ot = self.check(e.obj)
        o = ot.resolved() if ot is not None else None
        if isinstance(o, ArrayT):
            elem = o.elem
        elif isinstance(o, ManyT):
            elem = o.target
            if not elem.resolved().complete:
                raise YError("cannot index a pointer to the incomplete type %s" % elem, e.where)
        elif isinstance(o, PtrT) and isinstance(o.target.resolved(), ArrayT):
            raise YError("indexing does not dereference: write [p][i] for an element of the array p points to",
                         e.where)
        else:
            raise YError("only arrays and [*]T can be indexed, not %s" % ot, e.where)
        it = self.check(e.index)
        if it is None:
            self.coerce(e.index, INT16 if e.index.const < 0 else UINT16)
            it = e.index.ty
        if not is_int(it) or it.resolved().size > 2:
            raise YError("an index is an integer of up to 16 bits, not %s" % it, e.index.where)
        if isinstance(o, ArrayT) and e.index.const is not None and not 0 <= e.index.const < o.n:
            raise YError("index %d is outside 0 ... %d" % (e.index.const, o.n - 1), e.index.where)
        return elem

    def check_field(self, e: Node, expected: Type | None) -> Type:
        ot = self.check(e.obj)
        o = ot.resolved() if ot is not None else None
        if isinstance(o, PtrT) and isinstance(o.target.resolved(), StructT):
            raise YError("fields behind a pointer are reached as [p].%s" % e.name, e.where)
        if not isinstance(o, StructT):
            raise YError("only structs and unions have fields, not %s" % ot, e.where)
        f = o.field(e.name)
        if f is None:
            raise YError("%s has no field '%s'" % (ot, e.name), e.where)
        e.offset = f[0]
        return f[1]

    def check_deref(self, e: Node, expected: Type | None) -> Type:
        pt = self.check(e.ptr)
        p = pt.resolved() if pt is not None else None
        if not isinstance(p, (PtrT, ManyT)):
            raise YError("only pointers can be dereferenced, not %s" % pt, e.where)
        t = p.target
        if isinstance(t.resolved(), FnT):
            raise YError("a function pointer is called directly, f(…), not dereferenced", e.where)
        if not t.resolved().complete:
            raise YError("cannot dereference a pointer to the incomplete type %s" % t, e.where)
        return t

    def check_ptr(self, e: Node, expected: Type | None) -> Type:
        x = e.operand
        if x.kind == "name":
            sym = self.lookup(x.name, x.where)
            if sym.kind == "func":
                sym.used = True
                x.sym = sym
                x.ty = sym.ty
                return PtrT(sym.ty)
        t = self.check(x)
        if not self.is_lvalue(x):
            raise YError("@ptr needs a variable, a dereference, an element or a field", e.where)
        if x.kind == "index":
            return ManyT(t)
        return PtrT(t)

    def check_boolof(self, e: Node, expected: Type | None) -> Type:
        self.cond(e.operand)
        if e.operand.const is not None:
            e.const = e.operand.const
        return BOOL

    def check_as(self, e: Node, expected: Type | None) -> Type:
        t = self.resolve(e.type)
        if not t.resolved().complete:
            raise YError("@as to the incomplete type %s" % t, e.where)
        st = self.check(e.operand)
        if st is None:
            if not is_int(t):
                raise YError("a constant can only become an integer", e.where)
            self.coerce(e.operand, t)
        else:
            self.value(e.operand)
        return t

    def check_cast(self, e: Node, expected: Type | None) -> Type:
        t = self.resolve(e.type)
        st = self.check(e.operand)
        if st is None:
            if is_int(t):
                self.coerce(e.operand, t)
                st = t
            elif isinstance(t.resolved(), BoolT):
                e.const = int(e.operand.const != 0)
                return t
            else:
                raise YError("@cast to %s is not allowed" % t, e.where)
        self.value(e.operand)
        S, D = st.resolved(), t.resolved()
        ok = (isinstance(S, IntT) and isinstance(D, (IntT, BoolT))) or (isinstance(S, BoolT) and isinstance(D, (IntT, BoolT)))
        if not ok:
            raise YError("@cast from %s to %s is not allowed (only integers and bool; use @as)" % (st, t), e.where)
        if e.operand.const is not None:
            c = e.operand.const
            e.const = int(c != 0) if isinstance(D, BoolT) else wrap(c, D)
        return t

    def check_init(self, e: Node, expected: Type | None) -> Type:
        raise YError("an initialiser '{…}' is only allowed where its type is known", e.where)

    # -- contexts -------------------------------------------------------------------------------

    def cond(self, e: Node) -> None:
        """e is used as a condition: a comparison, logic, or a bool value."""
        t = self.check(e)
        if t is COND:
            return
        if t is not None and isinstance(t.resolved(), BoolT):
            return
        raise YError("a condition is needed here (a comparison, not/and/or, or a bool), not %s"
                     % ("a constant" if t is None else t), e.where)

    def value(self, e: Node) -> None:
        t = e.ty
        if t is COND:
            raise YError("a condition is not a value; write @bool(…)", e.where)
        if t is VOID:
            raise YError("this call gives no value", e.where)
        if isinstance(t, FnT) or (t is not None and isinstance(t.resolved(), FnT)):
            raise YError("a function is not a value; take its address with @ptr", e.where)

    def coerce(self, e: Node, target: Type) -> None:
        """e (an expression or an initialiser) is stored as / passed as `target`."""
        if e.kind == "init":
            self.check_init_as(e, target)
            return
        if e.ty is None and e.const is None:
            self.check(e, target)
        t = e.ty
        if t is None:
            T = target.resolved()
            if isinstance(T, IntT):
                lo_, hi_ = T.range()
                if not lo_ <= e.const <= hi_:
                    raise YError("the constant %d does not fit in %s" % (e.const, target), e.where)
                e.ty = target
                return
            raise YError("a constant cannot become %s" % target, e.where)
        self.value(e)
        if same(t, target):
            return
        if implicit(t, target):
            e.conv = target
            return
        raise YError("cannot use %s as %s" % (t, target), e.where)

    def check_init_as(self, e: Node, target: Type) -> None:
        T = target.resolved()
        e.ty = target
        if isinstance(T, ArrayT):
            if e.elems is None:
                raise YError("an array is initialised with values, not fields", e.where)
            if len(e.elems) > T.n or (len(e.elems) < T.n and not e.fill):
                raise YError("%d values for an array of %d" % (len(e.elems), T.n), e.where)
            for el in e.elems:
                self.check_value_as(el, T.elem)
        elif isinstance(T, StructT):
            if e.fields is None:
                raise YError("a %s is initialised with named fields: {name = value, …}"
                             % ("union" if T.union else "struct"), e.where)
            seen = set()
            for name, val, fw in e.fields:
                f = T.field(name)
                if f is None:
                    raise YError("%s has no field '%s'" % (target, name), fw)
                if name in seen:
                    raise YError("field '%s' twice" % name, fw)
                seen.add(name)
                self.check_value_as(val, f[1])
            if T.union and len(e.fields) != 1:
                raise YError("a union initialiser names exactly one field", e.where)
            if not T.union and len(seen) != len(T.fields):
                missing = [n for n, _ in T.fields if n not in seen]
                raise YError("field%s %s not initialised" % ("s" if len(missing) > 1 else "",
                             ", ".join(missing)), e.where)
        else:
            raise YError("an initialiser '{…}' needs an array, struct or union type, not %s" % target, e.where)

    def check_value_as(self, e: Node, target: Type) -> None:
        if e.kind != "init":
            self.check(e, target)
        self.coerce(e, target)

    def is_lvalue(self, e: Node) -> bool:
        if e.kind == "name":
            return getattr(e, "sym", None) is not None and e.sym.kind == "var"
        if e.kind == "deref":
            return True
        if e.kind == "index":
            return isinstance(e.obj.ty.resolved(), ManyT) or self.is_lvalue(e.obj)
        if e.kind == "field":
            return self.is_lvalue(e.obj)
        return False

    # -- top level -------------------------------------------------------------------------------

    def compile(self, items: list[Node]) -> str:
        for item in items:
            getattr(self, "top_" + item.kind)(item)
        self.compile_helpers()
        return self.output()

    def top_decl(self, d: Node) -> None:
        old = self.find(d.name)
        if old is not None:
            raise YError("'%s' is already declared (at %s:%d)" % (d.name, old.where[0], old.where[1]), d.where)
        if d.is_type:
            sym = Sym("type", d.name, NamedT(d.name), d.where)
        else:
            t = self.resolve(d.type)
            sym = Sym("func" if isinstance(t.resolved(), FnT) else "var", d.name, t, d.where)
            if sym.kind == "var":
                if d.recursive:
                    raise YError("@recursive applies to functions only", d.where)
                sym.loc = GlobalLoc(d.name)
            sym.recursive = d.recursive
        sym.declared = True
        self.scopes[0][d.name] = sym

    def top_typedef(self, d: Node) -> None:
        old = self.find(d.name)
        if old is not None:
            if old.kind != "type" or not isinstance(old.ty, NamedT) or old.defined:
                raise YError("'%s' is already declared (at %s:%d)" % (d.name, old.where[0], old.where[1]), d.where)
            named = old.ty
        else:
            named = NamedT(d.name)
            old = Sym("type", d.name, named, d.where)
            self.scopes[0][d.name] = old
        t = self.resolve(d.type)
        if t.resolved() is named:
            raise YError("type '%s' is defined as itself" % d.name, d.where)
        named.target = t
        if isinstance(t, StructT) and t.name is None:
            t.name = d.name
        old.defined = True

    def define(self, kind: str, name: str, ty: Type, where: tuple[str, int], internal: bool,
               recursive: bool = False) -> Sym:
        old = self.find(name)
        if old is not None:
            if not old.declared or old.defined or old.kind != kind:
                raise YError("'%s' is already declared (at %s:%d)" % (name, old.where[0], old.where[1]), where)
            if not same(old.ty, ty):
                raise YError("'%s' is defined as %s but declared as %s" % (name, ty, old.ty), where)
            if old.recursive != recursive:
                raise YError("'%s' is %s@recursive here but %s in its decl" % (
                    name, "" if recursive else "not ", "is" if old.recursive else "is not"), where)
            sym = old
        else:
            sym = Sym(kind, name, ty, where)
            self.scopes[0][name] = sym
        sym.defined = True
        sym.internal = internal
        sym.recursive = recursive
        return sym

    def top_impl(self, d: Node, helper: bool = False) -> None:
        params = [self.resolve(t) for _, t, _ in d.params]
        ret = self.resolve(d.ret) if d.ret else None
        fnty = FnT(params, ret, [n for n, _, _ in d.params])
        sym = self.define("func", d.name, fnty, d.where, d.internal, d.recursive)
        sym.helper = helper
        if d.main:
            if self.main is not None:
                raise YError("only one @main per file", d.where)
            if params or ret is not None:
                raise YError("the @main function takes no parameters and returns nothing", d.where)
            self.main = sym
        for p in params + ([ret] if ret else []):
            if not p.resolved().complete:
                raise YError("parameters and results need complete types, not %s" % p, d.where)
        gen = FuncGen(self, d, sym, fnty)
        self.fn = gen
        lines = gen.run()
        self.fn = None
        self.code_sections.append((d.section, lines))
        if not sym.recursive:
            self.frames.append((gen.frame, gen.size, not d.internal, gen.layout_text()))

    def top_var(self, d: Node) -> None:
        infer = None
        if d.type.kind == "tarray" and d.type.length is None:
            infer = infer_length(d.value, d.where)
        t = self.resolve(d.type, infer)
        if not t.resolved().complete:
            raise YError("the variable '%s' has the incomplete type %s" % (d.name, t), d.where)
        if d.value is not None:
            self.check_value_as(d.value, t)
        sym = self.define("var", d.name, t, d.where, d.internal)
        sym.loc = GlobalLoc(d.name)
        items: list = []
        if d.value is not None:
            self.static_value(d.value, t, items)
        if d.value is None or all(x == 0 for x in expand_items(items)):
            # undefined, or all zero: .bss, which the start-up code zeroes
            self.bss.append("%s:%s" % (d.name, "" if d.value is None else
                                       " " * max(1, 39 - len(d.name)) + "; zero: in .bss, zeroed at start-up"))
            self.bss.append("        .res %d" % t.resolved().size)
        else:
            self.data.append("%s:" % d.name)
            self.data.extend(data_lines(items))

    # -- static data -------------------------------------------------------------------------------

    def string_label(self, data: list[int]) -> str:
        label = "str.%d" % (len(self.strings) + 1)
        self.strings.append((label, data))
        return label

    def static_value(self, e: Node, t: Type, out: list) -> None:
        """Append the bytes of a constant initial value: ints, or ('addr', label, off)."""
        T = t.resolved()
        if e.kind == "init":
            if isinstance(T, ArrayT):
                elem = T.elem
                for el in e.elems:
                    self.static_value(el, elem, out)
                for _ in range(T.n - len(e.elems)):
                    self.static_value(e.elems[-1], elem, out)
            else:
                start = len(out)
                buf: list = [0] * T.size
                for name, val, _ in e.fields:
                    off, ft = T.field(name)
                    part: list = []
                    self.static_value(val, ft, part)
                    flat = expand_items(part)
                    buf[off:off + len(flat)] = flat
                out.extend(compact_items(buf))
                del start
            return
        if e.kind == "str":
            out.extend(e.data + [0])
            return
        if e.kind == "sstr":
            out.append(("addr", self.string_label(e.data), 0))
            return
        if e.kind == "ptr":
            label, off = self.static_address(e.operand)
            out.append(("addr", label, off))
            return
        if e.const is not None:
            out.extend(le_bytes(e.const, T.size))
            return
        raise YError("the initial value of a global variable must be a constant", e.where)

    def static_address(self, x: Node) -> tuple[str, int]:
        if x.kind == "name":
            sym = x.sym
            if sym.kind == "func" or isinstance(sym.loc, GlobalLoc):
                if sym.kind == "func":
                    sym.addressed = True
                return sym.name, 0
        if x.kind == "field":
            label, off = self.static_address(x.obj)
            return label, off + x.offset
        if x.kind == "index" and isinstance(x.obj.ty.resolved(), ArrayT) and x.index.const is not None:
            label, off = self.static_address(x.obj)
            return label, off + x.index.const * x.ty.resolved().size
        raise YError("@ptr in a global initial value must name a global variable or function", x.where)

    # -- helpers for * / % ------------------------------------------------------------------------

    def compile_helpers(self) -> None:
        """The assembly routines for * / % that this file uses (prelude.py)."""
        for name in sorted(self.helpers_used):
            lines, size, layout = prelude.routine(name)
            self.code_sections.append((None, lines))
            self.frames.append((name + ".frame", size, False, layout))

    def helper(self, op: str, t: IntT) -> Sym:
        name = prelude.helper_name(op, t.bits, t.signed)
        self.helpers_used.add(name)
        sym = Sym("func", name, FnT([t, t], t), ("<ylangc helpers>", 0))
        sym.helper = True
        sym.internal = True
        return sym

    # -- output --------------------------------------------------------------------------------------

    def output(self) -> str:
        g = self.scopes[0]
        imports = []
        for sym in sorted(g.values(), key=lambda x: x.name):
            if sym.kind in ("var", "func") and sym.declared and not sym.defined and sym.used:
                imports.append(sym.name)
                if sym.kind == "func" and sym.called and not sym.recursive:
                    imports.append(sym.name + ".frame")
        exports = []
        for sym in g.values():
            if sym.kind in ("var", "func") and sym.defined and not sym.internal:
                exports.append(sym.name)
                if sym.kind == "func" and not sym.recursive:
                    exports.append(sym.name + ".frame")
        out = ["; generated by ylangc %s (ABI 0.4, docs/ylangc.md)" % VERSION, ""]
        if self.main is not None:
            imports += ["__stack_top", "__bss_start", "__bss_end"]
        for name in imports:
            out.append("        .import %s" % name)
        for name in exports:
            out.append("        .export %s" % name)
        if self.main is not None:
            out += ["", "; start-up code at address 0: set the stack pointer, zero .bss, run the @main function, stop",
                    "        .code vector", "        .export _start",
                    "_start: mova    r14a, =__stack_top     ; SP = the last byte of RAM; the stack grows down",
                    "        mova    r2a, =__bss_start      ; zero .bss (all files): r2a = the next byte ...",
                    "        mova    r4a, =__bss_end        ; ... up to r4a",
                    "        mov     r0, #0",
                    ".l zero:",
                    "        cmp     r2, r4                 ; r2a - r4a",
                    "        subcd   r3, r5",
                    "        br.geu  .f =zeroed             ; reached the end",
                    "        sti     r0, r2a, #1            ; zero a byte, r2a + 1",
                    "        br      .b =zero",
                    ".l zeroed:",
                    "        brl     r12a, =%-18s ; call %s" % (self.main.name, self.main.name),
                    ".l spin:",
                    "        br      .b =spin               ; %s returned: stop here" % self.main.name]
        for section, lines in self.code_sections:
            out.append("")
            out.append("        .code %s" % section if section else "        .code")
            for item in lines:
                if isinstance(item, tuple):         # ("header", sym, lines)
                    _, sym, header = item
                    if not sym.internal or sym.addressed:
                        out.extend(header)
                else:
                    out.append(item)
        if self.data or self.strings:
            out += ["", "        .data"]
            out.extend(self.data)
            for label, data in self.strings:
                out.append("%s:" % label)
                out.extend(data_lines(data + [0]))
        if self.bss or self.frames:
            out += ["", "        .bss"]
            out.extend(self.bss)
            for label, size, _, layout in self.frames:
                out.append("")
                out.extend(layout)
                out.append("%s:" % label)
                out.append("        .res %d" % size)
        return "\n".join(out) + "\n"


def infer_length(value: Node | None, where: tuple[str, int]) -> int:
    if value is not None and value.kind == "str":
        return len(value.data) + 1
    if value is not None and value.kind == "init" and value.elems is not None:
        if value.fill:
            raise YError("'_' cannot fill a [_] array: its length is unknown", value.where)
        return len(value.elems)
    raise YError("'[_]' needs a string or a list of values to take the length from", where)


def expand_items(items: list) -> list:
    out = []
    for it in items:
        if isinstance(it, tuple):
            out.extend([it, None])
        else:
            out.append(it)
    return out


def compact_items(buf: list) -> list:
    return [b for b in buf if b is not None]


def data_lines(items: list) -> list[str]:
    lines = []
    run: list[int] = []

    def flush() -> None:
        for i in range(0, len(run), 16):
            lines.append("        .byte %s" % ", ".join(str(b) for b in run[i:i + 16]))
        run.clear()

    for it in items:
        if isinstance(it, tuple):
            flush()
            _, label, off = it
            lines.append("        .addr =%s%s" % (label, "+%d" % off if off else ""))
        else:
            run.append(it)
    flush()
    return lines


def wrap(v: int, t: Type) -> int:
    T = t.resolved()
    if not isinstance(T, IntT):
        return v
    v &= (1 << T.bits) - 1
    if T.signed and v >= 1 << (T.bits - 1):
        v -= 1 << T.bits
    return v


def fold(op: str, a: int, b: int, where: tuple[str, int]) -> int:
    if op in ("/", "%") and b == 0:
        raise YError("division by zero in a constant expression", where)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        q = abs(a) // abs(b)
        return q if (a < 0) == (b < 0) else -q
    if op == "%":
        r = abs(a) % abs(b)
        return -r if a < 0 else r
    if op == "&":
        return a & b
    if op == "|":
        return a | b
    if op == "^":
        return a ^ b
    if op == "shl":
        return a << b
    if op in ("shr", "sar"):
        return a >> b
    raise YError("'%s' of constants needs a type" % op, where)


def fold_shift(op: str, a: int, n: int, t: IntT) -> int:
    w = t.bits
    m = (1 << w) - 1
    u = a & m
    if op == "shl":
        r = (u << n) & m if n < w else 0
    elif op == "shr":
        r = u >> n if n < w else 0
    elif op == "sar":
        sv = u - (1 << w) if u >> (w - 1) else u        # the bits read as signed
        r = (sv >> min(n, w)) & m
    else:
        n %= w
        if op == "rol":
            r = ((u << n) | (u >> (w - n))) & m
        else:
            r = ((u >> n) | (u << (w - n))) & m
    return wrap(r, t)


# ---------------------------------------------------------------------------------------------
# code generation of one function
# ---------------------------------------------------------------------------------------------

def show(e: Node, limit: int = 40) -> str:
    """A short source-like text of an expression, for comments."""
    text = _show(e)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _show(e: Node) -> str:
    k = e.kind
    if k == "int":
        return str(e.value)
    if k in ("true", "false", "nullptr"):
        return k
    if k == "name":
        return e.name
    if k == "str":
        return '"%s"' % "".join(chr(c) if 32 <= c < 127 else "." for c in e.data)
    if k == "sstr":
        return 's"%s"' % "".join(chr(c) if 32 <= c < 127 else "." for c in e.data)
    if k == "unary":
        return "%s%s%s" % (e.op, " " if e.op == "not" else "", _paren(e.operand))
    if k == "binary":
        return "%s %s %s" % (_paren(e.left), e.op, _paren(e.right))
    if k == "call":
        return "%s(%s)" % (_show(e.func), ", ".join(_show(a) for a in e.args))
    if k == "index":
        return "%s[%s]" % (_paren(e.obj), _show(e.index))
    if k == "field":
        return "%s.%s" % (_paren(e.obj), e.name)
    if k == "deref":
        return "[%s]" % _show(e.ptr)
    if k == "ptr":
        return "@ptr(%s)" % _show(e.operand)
    if k == "boolof":
        return "@bool(%s)" % _show(e.operand)
    if k == "sizeof":
        return "@sizeof(...)"
    if k in ("as", "cast"):
        return "@%s(%s, %s)" % (k, e.ty, _show(e.operand))
    if k == "init":
        return "{...}"
    return k


def _paren(e: Node) -> str:
    return "(%s)" % _show(e) if e.kind == "binary" else _show(e)


# -- peephole: branches -------------------------------------------------------------------------------------

INVERSE = {"eq": "ne", "ne": "eq", "mi": "pl", "pl": "mi", "vs": "vc", "vc": "vs", "su": "geu", "geu": "su",
           "gu": "seu", "seu": "gu", "ss": "ges", "ges": "ss", "gs": "ses", "ses": "gs"}


def asm_line(ins: str, ops: str, comment: str = "") -> str:
    text = "%-7s %s" % (ins, ops) if ops else ins
    return "        %-30s ; %s" % (text, comment) if comment else "        " + text


def parse_line(s: str) -> tuple:
    """("label", name) | ("ins", mnemonic, operands, comment) | ("other",)"""
    if not s.strip() or s.lstrip().startswith(";"):
        return ("other",)
    if not s[0].isspace():
        return ("label", s.split(":")[0])
    code, _, comment = s.partition(";")
    ins, _, ops = code.strip().partition(" ")
    return ("ins", ins, ops.strip(), comment.strip())


def peephole(lines: list[str]) -> list[str]:
    """Branch clean-up within one function, repeated until nothing changes:
    code after an unconditional br up to the next label is unreachable; a
    branch to a label that holds just `br =X` goes to X; a branch to the
    next instruction is dropped; `br.cc =A / br =B / A:` becomes `br.!cc =B`."""
    while True:
        P = [parse_line(s) for s in lines]
        changed = False
        # labels nothing refers to (any more)
        used = {m.group(1) for p in P if p[0] == "ins" for m in re.finditer(r"=([\w.]+)", p[2])}
        keep = [s for s, p in zip(lines, P) if p[0] != "label" or p[1] in used]
        if len(keep) != len(lines):
            changed = True
            lines = keep
            P = [parse_line(s) for s in lines]
        # unreachable code
        keep, dead = [], False
        for s, p in zip(lines, P):
            if p[0] == "label":
                dead = False
            if dead and p[0] == "ins":
                changed = True
                continue
            keep.append(s)
            if p[0] == "ins" and p[1] == "br":
                dead = True
        lines = keep
        P = [parse_line(s) for s in lines]
        where = {p[1]: i for i, p in enumerate(P) if p[0] == "label"}

        def next_ins(i: int) -> tuple[int | None, set]:
            """The next instruction after line i and the labels before it."""
            labels = set()
            for j in range(i + 1, len(P)):
                if P[j][0] == "label":
                    labels.add(P[j][1])
                elif P[j][0] == "ins":
                    return j, labels
            return None, labels

        out = list(lines)
        drop = set()
        for i, p in enumerate(P):
            if p[0] != "ins" or i in drop or not (p[1] == "br" or p[1].startswith("br.")) or not p[2].startswith("="):
                continue
            ins, target, comment = p[1], p[2][1:], p[3]
            # thread through labels that only branch on
            seen = {target}
            while target in where:
                j, _ = next_ins(where[target])
                if j is None or P[j][1] != "br" or not P[j][2].startswith("=") or P[j][2][1:] in seen:
                    break
                target = P[j][2][1:]
                seen.add(target)
            if "=" + target != p[2]:
                out[i] = asm_line(ins, "=" + target, comment)
                changed = True
            j, labels = next_ins(i)
            if target in labels:
                drop.add(i)                                     # a branch to the next instruction
                changed = True
                continue
            if ins.startswith("br.") and j is not None and j not in drop and P[j][1] == "br" \
                    and P[j][2].startswith("=") and ins[3:] in INVERSE:
                k, after = next_ins(j)
                if target in after:
                    out[i] = asm_line("br." + INVERSE[ins[3:]], P[j][2], P[j][3] or comment)
                    drop.add(j)
                    changed = True
        lines = [s for i, s in enumerate(out) if i not in drop]
        if not changed:
            # a source line comment right after the same one says nothing new
            last = None
            out = []
            for s in lines:
                if s.startswith("; line "):
                    if s == last:
                        continue
                    last = s
                elif not s.startswith(";") and s.strip():
                    if parse_line(s)[0] == "ins":
                        last = None
                out.append(s)
            return out


class FuncGen:
    """Code of one function, with its static frame `name.frame`."""

    def __init__(self, module: Module, d: Node, sym: Sym, fnty: FnT) -> None:
        self.m = module
        self.d = d
        self.sym = sym
        self.fnty = fnty
        self.frame = sym.name + ".frame"
        self.size = 0                        # bytes of the frame so far
        self.layout: list[tuple[int, int, str]] = []
        self.code: list[str] = []
        self.free = set(REGS)
        self.live: list[Temp] = []           # temps in registers, oldest first
        self.pool: dict[int, list[GlobalLoc]] = {}
        self.nlabel = 0
        self.ntemp = 0
        self.loops: list[tuple[str | None, str, str]] = []
        self.recursive = sym.recursive
        self.sp_delta = 0                    # bytes pushed below the frame (calls of @recursive functions)
        self.ret_label = self.label()
        R = fnty.ret.resolved().size if fnty.ret else 0
        if self.recursive:
            self.ret_loc = StackLoc(Slot(R, "caller", 0, "result")) if R else None
            self.param_locs = []
            off = R
            for (name, _, _), t in zip(d.params, fnty.params):
                size = t.resolved().size
                self.param_locs.append(StackLoc(Slot(size, "caller", off, name)))
                off += size
            self.caller_area = off
            self.lr_loc = StackLoc(Slot(2, "lr", 0, "saved return address (r12a)"))
        else:
            self.ret_loc = self.slot(R, "result") if R else None
            self.param_locs = [self.slot(t.resolved().size, name)
                               for (name, _, _), t in zip(d.params, fnty.params)]
            self.lr_loc = self.slot(2, "saved return address (r12a)")

    # -- the frame ------------------------------------------------------------------------------------

    def slot(self, size: int, desc: str):
        """size bytes of this function's frame: static, or on the stack."""
        base = self.size
        self.size += size
        self.layout.append((base, size, desc))
        if self.recursive:
            return StackLoc(Slot(size, "local", base, desc))
        return GlobalLoc(self.frame, base, desc)

    def layout_text(self) -> list[str]:
        if self.recursive:
            L = self.size
            F = L + 2
            out = ["; stack frame of %s, %d bytes, SP + 1 ... SP + %d after the prologue:" % (self.sym.name, F, F)]
            for base, size, desc in self.layout:
                out.append(";   SP+%-4d %-3d %s" % (1 + base, size, desc))
            out.append(";   SP+%-4d 2   saved return address (r12a)" % (1 + L))
            if self.ret_loc is not None:
                out.append(";   SP+%-4d %-3d result (the caller's area)" % (1 + F, self.ret_loc.slot.size))
            for loc in self.param_locs:
                out.append(";   SP+%-4d %-3d %s (the caller's area)" % (1 + F + loc.slot.off, loc.slot.size, loc.desc))
            return out
        out = ["; frame of %s, %d bytes (ABI 0.4: the caller writes the arguments here)" % (self.sym.name, self.size)]
        for base, size, desc in self.layout:
            out.append(";   +%-4d %-3d %s" % (base, size, desc))
        return out

    def emit(self, ins: str, ops: str = "", comment: str = "") -> None:
        if ins.split(".")[0] not in READ_ONLY:
            # a write to the registers of a constant temp: it is no longer known
            used = set()
            for m in re.finditer(r"\br(\d+)(a?)\b", ops):
                r = int(m.group(1))
                used.update((r, r + 1) if m.group(2) else (r,))
            for t in self.live:
                if t.const_bytes is not None and used & set(t.regs):
                    t.const_bytes = None
        text = "%-7s %s" % (ins, ops) if ops else ins
        self.code.append("        %-30s ; %s" % (text, comment) if comment else "        " + text)

    def label(self) -> str:
        self.nlabel += 1
        return "%s.%d" % (self.sym.name, self.nlabel)

    def place(self, label: str, comment: str = "") -> None:
        self.code.append("%s:%s" % (label, "%s; %s" % (" " * max(1, 39 - len(label)), comment) if comment else ""))

    # -- temps ----------------------------------------------------------------------------------------------

    def alloc(self, size: int) -> list[int]:
        while len(self.free) < size:
            victim = next((t for t in self.live if not t.pinned), None)
            if victim is None:
                raise AssertionError("out of registers")
            self.spill(victim)
        regs = sorted(self.free)[:size]
        for r in regs:
            self.free.discard(r)
        return regs

    def temp(self, size: int, desc: str) -> Temp:
        t = Temp(size, desc)
        t.regs = self.alloc(size)
        self.live.append(t)
        return t

    def spill(self, t: Temp) -> None:
        if t.regs is None:
            return
        if t.const_bytes is not None:            # re-created by ensure()
            self.free.update(t.regs)
            t.regs = None
            self.live.remove(t)
            return
        if t.slot is None:
            pool = self.pool.get(t.size)
            t.slot = pool.pop() if pool else self.slot(t.size, "spill slot")
        for k in range(t.size):
            self.byte_op("str", t.r(k), t.slot, k, "spill %s" % byte_desc(t.desc, k, t.size))
        self.free.update(t.regs)
        t.regs = None
        self.live.remove(t)

    def ensure(self, t: Temp) -> Temp:
        if t.regs is None and t.const_bytes is not None:
            regs = self.alloc(t.size)
            for k, r in enumerate(regs):
                self.code.append(asm_line("mov", "r%d, #%d" % (r, t.const_bytes[k]),
                                          "r%d = %s" % (r, byte_desc(t.desc, k, t.size))))
            t.regs = regs
            self.live.append(t)
            return t
        if t.regs is None:
            regs = self.alloc(t.size)
            for k, r in enumerate(regs):
                self.byte_op("ldr", "r%d" % r, t.slot, k, "reload %s" % byte_desc(t.desc, k, t.size))
            t.regs = regs
            self.live.append(t)
        return t

    def pin(self, *ts: Temp) -> None:
        for t in ts:
            t.pinned += 1

    def unpin(self, *ts: Temp) -> None:
        for t in ts:
            t.pinned -= 1

    def release(self, t: Temp) -> None:
        if t.dead:
            return
        t.dead = True
        if t.regs is not None:
            self.free.update(t.regs)
            self.live.remove(t)
            t.regs = None
        if t.slot is not None:
            self.pool.setdefault(t.size, []).append(t.slot)

    def spill_all(self) -> None:
        for t in list(self.live):
            self.spill(t)

    def forget_reloads(self) -> None:
        """Like spill_all, after code that only reloaded temps from their
        slots (writing the arguments of a call): a temp with a slot still
        holds its value there, so its registers are just dropped."""
        for t in list(self.live):
            if t.slot is None and t.const_bytes is None:
                self.spill(t)
            else:
                self.free.update(t.regs)
                t.regs = None
                self.live.remove(t)

    def resize(self, t: Temp, size: int) -> None:
        """Drop the high bytes of t (size < t.size)."""
        for r in t.regs[size:]:
            self.free.add(r)
        t.regs = t.regs[:size]
        t.size = size
        t.slot = None                      # the old slot has the wrong size
        t.const_bytes = None

    def extend(self, t: Temp, size: int, signed: bool) -> None:
        if size <= t.size:
            return
        self.pin(t)
        extra = self.alloc(size - t.size)
        self.unpin(t)
        top = t.r(t.size - 1)
        if signed:
            self.emit("mov", "r%d, #0" % extra[0], "sign extension of %s: 0 ..." % t.desc)
            self.emit("andd", "%s, #128" % top, "... is the sign bit set?")
            self.emit("mov.ne", "r%d, #255" % extra[0], "... then 0xFF")
            for r in extra[1:]:
                self.emit("mov", "r%d, r%d" % (r, extra[0]), "sign extension, next byte")
        else:
            for r in extra:
                self.emit("mov", "r%d, #0" % r, "zero extension of %s" % t.desc)
        t.regs = t.regs + extra
        t.size = size
        t.slot = None
        t.const_bytes = None

    def const(self, value: int, size: int, desc: str | None = None) -> Temp:
        t = self.temp(size, desc or str(value))
        for k, b in enumerate(le_bytes(value, size)):
            self.emit("mov", "%s, #%d" % (t.r(k), b), "%s = %s" % (t.r(k), byte_desc(t.desc, k, size)))
        t.const_bytes = le_bytes(value, size)
        return t

    # -- memory --------------------------------------------------------------------------------------------

    def byte_op(self, op: str, reg: str, loc, k: int, comment: str) -> None:
        """ldr/str reg <-> byte k of loc."""
        if isinstance(loc, GlobalLoc):
            self.emit(op, "%s, %s" % (reg, loc.operand(k)), comment)
        elif isinstance(loc, StackLoc):
            self.code.append(("stk", "ldo" if op == "ldr" else "sto", reg, loc.slot, loc.off + k, self.sp_delta,
                              comment))
        elif isinstance(loc, SpLoc):
            off = 1 + loc.off + k + self.sp_delta - loc.delta
            self.emit("ldo" if op == "ldr" else "sto", "%s, r14a, #%d" % (reg, off), comment)
        else:
            self.ptr_prepare(loc)
            at = self.ptr_setup(loc, k, k)
            self.emit("ldo" if op == "ldr" else "sto", "%s, %s" % (reg, at(k)), comment)
            self.unpin(*loc.temps())

    def ptr_prepare(self, loc: "PtrLoc") -> None:
        """The temps of loc into registers and pinned; the index into a
        register pair if one is free (for `r10a, rIa`)."""
        for t in loc.temps():
            self.ensure(t)
            self.pin(t)
        i = loc.index
        if i is not None and i.regs[1] != i.regs[0] + 1:
            pair = next((x for x in range(len(REGS) - 1) if x in self.free and x + 1 in self.free), None)
            if pair is not None:
                for k in range(2):
                    self.emit("mov", "r%d, %s" % (pair + k, i.r(k)), "the index into a register pair" if k == 0 else "")
                self.free.update(i.regs)
                self.free.difference_update((pair, pair + 1))
                i.regs = [pair, pair + 1]

    def ptr_setup(self, loc: "PtrLoc", first: int, last: int):
        """r10a <- the address of loc (its temps prepared); returns a function
        giving the operands that reach byte k (first <= k <= last): `r10a, #n`,
        or `r10a, rIa` for one byte at the index itself."""
        off = loc.off
        if loc.temp is not None:
            t = loc.temp
            self.emit("mov", "r10, %s" % t.r(0), "r10a = address in %s" % t.regs_text())
            self.emit("mov", "r11, %s" % t.r(1))
        elif loc.base[0] == "mem":
            b = loc.base[1]
            self.emit("ldr", "r10, %s" % b.operand(0), "r10a = %s" % b.desc)
            self.emit("ldr", "r11, %s" % b.operand(1))
        else:
            b = loc.base[1].plus(off)
            off = 0
            desc = "r10a = @ptr(%s)" % loc.base[1].desc
            if isinstance(b, GlobalLoc):
                self.emit("mova", "r10a, %s" % b.operand(), desc)
            elif isinstance(b, StackLoc):
                self.code.append(("stk", "lea", "r10a", b.slot, b.off, self.sp_delta, desc))
            else:
                self.emit("lea", "r10a, r14a, #%d" % (1 + b.off + self.sp_delta - b.delta), desc)
        i = loc.index
        if i is not None:
            if i.regs[1] == i.regs[0] + 1:
                if first == last and off + first == 0:
                    return lambda k: "r10a, r%da" % i.regs[0]
                self.emit("lea", "r10a, r10a, r%da" % i.regs[0], "+ the index %s" % i.desc)
            else:
                self.emit("adds", "r10, r10, %s" % i.r(0), "+ the index %s" % i.desc)
                self.emit("addc", "r11, r11, %s" % i.r(1))
        if fits12(off + first) and fits12(off + last):
            return lambda k: "r10a, #%d" % (off + k)
        if fits12(off):
            self.emit("lea", "r10a, r10a, #%d" % off, "... + %d" % off)
        else:
            self.emit("adds", "r10, r10, #%d" % lo(off), "... + %d" % off)
            self.emit("addc", "r11, r11, #%d" % hi(off))
        return lambda k: "r10a, #%d" % k

    def load(self, loc, size: int, desc: str | None = None) -> Temp:
        if isinstance(loc, PtrLoc):
            self.ptr_prepare(loc)
            t = self.temp(size, desc or loc.desc)
            at = self.ptr_setup(loc, 0, size - 1)
            for k in range(size):
                self.emit("ldo", "%s, %s" % (t.r(k), at(k)), "%s = %s" % (t.r(k), byte_desc(loc.desc, k, size)))
            self.unpin(*loc.temps())
            return t
        t = self.temp(size, desc or loc.desc)
        for k in range(size):
            self.byte_op("ldr", t.r(k), loc, k, "%s = %s" % (t.r(k), byte_desc(loc.desc, k, size)))
        return t

    def store(self, loc, t: Temp) -> None:
        self.ensure(t)
        self.pin(t)
        if isinstance(loc, PtrLoc):
            self.ptr_prepare(loc)
            at = self.ptr_setup(loc, 0, t.size - 1)
            for k in range(t.size):
                self.emit("sto", "%s, %s" % (t.r(k), at(k)), "%s = %s" % (byte_desc(loc.desc, k, t.size), t.r(k)))
            self.unpin(t, *loc.temps())
            return
        self.unpin(t)
        for k in range(t.size):
            self.byte_op("str", t.r(k), loc, k, "%s = %s" % (byte_desc(loc.desc, k, t.size), t.r(k)))

    def free_loc(self, loc) -> None:
        if isinstance(loc, PtrLoc):
            for t in loc.temps():
                self.release(t)

    def addr_of(self, loc, consume: bool = True) -> Temp:
        """The address of loc as a 2-byte temp.  A PtrLoc's temps are reused
        or released (consumed) unless consume is False."""
        desc = "@ptr(%s)" % loc.desc
        if isinstance(loc, PtrLoc) and loc.index is None and loc.base is None:
            if consume:
                t = self.ensure(loc.temp)
                t.desc = desc
            else:
                src = self.ensure(loc.temp)
                self.pin(src)
                t = self.temp(2, desc)
                self.unpin(src)
                self.emit("mov", "%s, %s" % (t.r(0), src.r(0)), "copy the address in %s" % src.regs_text())
                self.emit("mov", "%s, %s" % (t.r(1), src.r(1)))
            if loc.off:
                self.emit("adds", "%s, %s, #%d" % (t.r(0), t.r(0), lo(loc.off)), "%s + %d" % (t.desc, loc.off))
                self.emit("addc", "%s, %s, #%d" % (t.r(1), t.r(1), hi(loc.off)))
            return t
        if isinstance(loc, PtrLoc):
            self.ptr_prepare(loc)
            t = self.temp(2, desc)
            at = self.ptr_setup(loc, 0, 0)
            n = int(at(0).split("#")[1]) if "#" in at(0) else None
            if n is None:                       # `r10a, rIa`: add the index
                self.emit("lea", "r10a, r10a, r%da" % loc.index.regs[0], "+ the index")
            elif n:
                self.emit("lea", "r10a, r10a, #%d" % n, "+ %d" % n)
            self.unpin(*loc.temps())
            if consume:
                self.free_loc(loc)
        else:
            t = self.temp(2, desc)
            if isinstance(loc, GlobalLoc):
                self.emit("mova", "r10a, %s" % loc.operand(), "r10a = %s" % desc)
            elif isinstance(loc, StackLoc):
                self.code.append(("stk", "lea", "r10a", loc.slot, loc.off, self.sp_delta, "r10a = %s" % desc))
            else:
                self.emit("lea", "r10a, r14a, #%d" % (1 + loc.off + self.sp_delta - loc.delta), "r10a = %s" % desc)
        self.emit("mov", "%s, r10" % t.r(0))
        self.emit("mov", "%s, r11" % t.r(1))
        return t

    def copy_loop(self, what: str, size: int) -> None:
        """Copy size bytes (at least 1) from r2a to r4a, forward, one at a time,
        with ldi / sti; the count is in r6 (r6a when size > 255)."""
        top = self.label()
        self.place(top, "copy loop: %s" % what)
        self.emit("ldi", "r0, r2a, #1", "r0 = byte at source, source + 1")
        self.emit("sti", "r0, r4a, #1", "byte at destination = r0, destination + 1")
        if size <= 255:
            self.emit("subs", "r6, r6, #1", "count - 1")
        else:
            self.emit("subs", "r6, r6, #1", "count - 1")
            self.emit("subc", "r7, r7, #0")
            self.emit("ord", "r6, r7", "count = 0?")
        self.emit("br.ne", "=%s" % top, "no: next byte")

    def copy(self, dst, src, size: int) -> None:
        """Copy size bytes, forward (so an overlapping copy from lower
        addresses repeats a pattern).  Neither location is consumed."""
        if size <= 0:
            return
        s = self.addr_of(src, consume=False)
        self.pin(s)
        d = self.addr_of(dst, consume=False)
        self.unpin(s)
        self.spill_all()
        for k, r in ((0, 2), (1, 3)):
            self.byte_op("ldr", "r%d" % r, s.slot, k, "r2a = source: %s" % src.desc if k == 0 else "")
        for k, r in ((0, 4), (1, 5)):
            self.byte_op("ldr", "r%d" % r, d.slot, k, "r4a = destination: %s" % dst.desc if k == 0 else "")
        self.release(s)
        self.release(d)
        self.emit("mov", "r6, #%d" % lo(size), "count = %d bytes" % size)
        if size > 255:
            self.emit("mov", "r7, #%d" % hi(size))
        self.copy_loop("%s = %s" % (dst.desc, src.desc), size)

    def run(self) -> list[str]:
        m = self.m
        m.scopes.append({})
        for (name, _, pw), t, loc in zip(self.d.params, self.fnty.params, self.param_locs):
            sym = Sym("var", name, t, pw)
            sym.loc = loc
            sym.defined = True
            m.declare(sym)
        self.block(self.d.body, new_scope=False)
        m.scopes.pop()
        name = self.sym.name
        rec = self.recursive
        L = self.size
        F = L + 2

        def line(ins: str, ops: str, comment: str = "") -> str:
            text = "%-7s %s" % (ins, ops)
            return "        %-30s ; %s" % (text, comment) if comment else "        " + text

        def stk(op: str, reg: str, slot: Slot, k: int, delta: int, comment: str) -> list[str]:
            base = slot.off if slot.kind == "local" else (L if slot.kind == "lr" else F + slot.off)
            off = 1 + base + k + delta
            target = "r10a" if op == "lea" else reg
            if fits12(off):
                return [line(op, "%s, r14a, #%d" % (target, off), comment)]
            out = [line("mova", "r10a, #%d" % (off & 0xFFFF), comment + " (far: SP + %d)" % off),
                   line("lea", "r10a, r14a, r10a")]
            if op != "lea":
                out.append(line(op, "%s, r10a, #0" % reg))
            return out

        def sp_move(n: int, comment: str) -> list[str]:
            if fits12(n):
                return [line("lea", "r14a, r14a, #%d" % n, comment)]
            return [line("mova", "r10a, #%d" % (n & 0xFFFF), comment), line("lea", "r14a, r14a, r10a")]

        # a leaf function calls nothing: r12a keeps the return address
        leaf = not any(isinstance(item, str) and item.lstrip().startswith("brl ") for item in self.code)
        out = ["", "; " + "-" * 78,
               "; %s: %s%s" % (name, self.fnty, " (@recursive: stack frame)" if rec else ""),
               "; " + "-" * 78]
        body: list[str] = []
        if rec:
            out += self.layout_text()
            header = [line(".addr", "0", "header: no static frame (@recursive) ..."),
                      line(".dword", "%d" % F, "... and the size of its stack frame")]
            body += sp_move(-F, "SP -= %d: the stack frame" % F)
            if not leaf:
                body += stk("sto", "r12", self.lr_loc.slot, 0, 0, "save the return address")
                body += stk("sto", "r13", self.lr_loc.slot, 1, 0, "")
        else:
            header = [line(".addr", "=%s" % self.frame, "header: the frame of %s ..." % name),
                      line(".dword", "%d" % self.size, "... and its size")]
            if not leaf:
                body += [line("str", "r12, %s" % self.lr_loc.operand(0), "save the return address"),
                         line("str", "r13, %s" % self.lr_loc.operand(1))]
        # the header is only needed by calls through a pointer: Module.output
        # drops it for an @internal function whose address is never taken
        out.append(("header", self.sym, header))
        out.append("%s:%s" % (name, "                                   ; leaf: r12a is never saved" if leaf else ""))
        for item in self.code:
            if isinstance(item, tuple):
                _, op, reg, slot, k, delta, comment = item
                body += stk(op, reg, slot, k, delta, comment)
            else:
                body.append(item)
        body.append("%s:%s; return" % (self.ret_label, " " * max(1, 39 - len(self.ret_label))))
        if rec:
            if not leaf:
                body += stk("ldo", "r12", self.lr_loc.slot, 0, 0, "reload the return address")
                body += stk("ldo", "r13", self.lr_loc.slot, 1, 0, "")
            body += sp_move(F, "SP += %d: free the stack frame" % F)
        elif not leaf:
            body.append(line("ldr", "r12, %s" % self.lr_loc.operand(0), "reload the return address"))
            body.append(line("ldr", "r13, %s" % self.lr_loc.operand(1)))
        body.append(line("br", "r12a", "back to the caller"))
        return out + peephole(body)

    def note(self, s: Node) -> None:
        text = self.m.texts.get(s.where)
        if text is not None:
            self.code.append("; line %d: %s" % (s.where[1], text.strip()))

    def block(self, b: Node, new_scope: bool = True) -> None:
        if new_scope:
            self.m.scopes.append({})
        for s in b.stmts:
            self.statement(s)
        if new_scope:
            self.m.scopes.pop()

    def statement(self, s: Node) -> None:
        assert not self.live, "temps alive between statements"
        if s.kind != "block":
            self.note(s)
        getattr(self, "st_" + s.kind)(s)
        self.spill_all()

    def st_block(self, s: Node) -> None:
        self.block(s)

    def st_var(self, s: Node) -> None:
        m = self.m
        infer = None
        if s.type.kind == "tarray" and s.type.length is None:
            infer = infer_length(s.value, s.where)
        t = m.resolve(s.type, infer)
        if not t.resolved().complete:
            raise YError("the variable '%s' has the incomplete type %s" % (s.name, t), s.where)
        if s.value is None:
            raise YError("a local variable needs an initial value; 'undefined' is for globals only", s.where)
        m.check_value_as(s.value, t)
        loc = self.slot(t.resolved().size, s.name)
        self.put(loc, s.value, t)
        sym = Sym("var", s.name, t, s.where)
        sym.loc = loc
        sym.defined = True
        m.declare(sym)

    def st_assign(self, s: Node) -> None:
        m = self.m
        tt = m.check(s.target)
        if tt is None or not m.is_lvalue(s.target):
            raise YError("only a variable, a dereference, an element or a field can be assigned", s.where)
        m.value(s.target)
        if s.op == "=":
            m.check_value_as(s.value, tt)
            if is_aggregate(tt):
                loc = self.loc(s.target)
                self.put(loc, s.value, tt)
                self.free_loc(loc)
            else:
                v = self.val(s.value)
                loc = self.loc(s.target, once=True)
                self.store(loc, v)
                self.release(v)
                self.free_loc(loc)
            return
        op = s.op[:-1]
        fake = Node("binary", s.where, op=op, left=s.target, right=s.value)
        rt = m.check(fake, tt)
        if rt is None or not same(rt, tt):
            raise YError("'%s' needs both sides of type %s" % (s.op, tt), s.where)
        loc = self.loc(s.target)
        cur = self.load(loc, tt.resolved().size, show(s.target))
        res = self.binop(op, cur, s.value, tt, show(fake))
        self.store(loc, res)
        self.release(res)
        self.free_loc(loc)

    def st_callstmt(self, s: Node) -> None:
        t = self.m.check(s.call)
        if t is not VOID:
            raise YError("the result of this call is not used; write '_ = …' to discard it", s.where)
        self.call(s.call)

    def st_discard(self, s: Node) -> None:
        t = self.m.check(s.value)
        if t is COND:
            raise YError("a condition is not a value", s.where)
        if t is VOID:
            raise YError("this call gives no value; call it without '_ ='", s.where)
        if t is None or s.value.const is not None:
            return
        if is_aggregate(t):
            self.free_loc(self.loc(s.value))
        else:
            self.release(self.val(s.value))

    def st_if(self, s: Node) -> None:
        self.m.cond(s.cond)
        then, other, end = self.label(), self.label(), self.label()
        self.branch(s.cond, then, other)
        self.place(then, "then: %s" % show(s.cond))
        self.block(s.then)
        self.emit("br", "=%s" % end, "skip the else part")
        self.place(other, "else" if s.els is not None else "not: %s" % show(s.cond))
        if s.els is not None:
            self.block(s.els)
        self.place(end, "end of if")

    def st_loop(self, s: Node) -> None:
        if s.name is not None and any(n == s.name for n, _, _ in self.loops):
            raise YError("loop '%s' is inside a loop of the same name" % s.name, s.where)
        top, end = self.label(), self.label()
        self.place(top, "loop " + s.name if s.name else "loop")
        self.loops.append((s.name, top, end))
        self.block(s.body)
        self.loops.pop()
        self.emit("br", "=%s" % top, "again")
        self.place(end, "end of loop " + s.name if s.name else "end of loop")

    def find_loop(self, s: Node) -> tuple[str | None, str, str]:
        if not self.loops:
            raise YError("'%s' outside a loop" % s.kind, s.where)
        if s.name is None:
            return self.loops[-1]
        for lp in reversed(self.loops):
            if lp[0] == s.name:
                return lp
        raise YError("no enclosing loop named '%s'" % s.name, s.where)

    def st_break(self, s: Node) -> None:
        self.emit("br", "=%s" % self.find_loop(s)[2], "break")

    def st_continue(self, s: Node) -> None:
        self.emit("br", "=%s" % self.find_loop(s)[1], "continue")

    def st_return(self, s: Node) -> None:
        ret = self.fnty.ret
        if s.value is None:
            if ret is not None:
                raise YError("this function returns %s; 'return' needs a value" % ret, s.where)
        else:
            if ret is None:
                raise YError("this function returns nothing", s.where)
            self.m.check_value_as(s.value, ret)
            self.put(self.ret_loc, s.value, ret)
        self.emit("br", "=%s" % self.ret_label, "return")

    # -- storing values ----------------------------------------------------------------------------------

    def put(self, loc, e: Node, t: Type) -> None:
        """Store the (checked) value or initialiser e of type t at loc."""
        T = t.resolved()
        if e.kind == "init":
            if isinstance(T, ArrayT):
                esize = T.elem.resolved().size
                for i, el in enumerate(e.elems):
                    self.put(loc.plus(i * esize, "%s[%d]" % (loc.desc, i)), el, T.elem)
                rest = T.n - len(e.elems)
                if rest > 0:
                    last = len(e.elems) - 1
                    self.copy(loc.plus(len(e.elems) * esize, "%s[%d...]" % (loc.desc, len(e.elems))),
                              loc.plus(last * esize, "%s[%d...]" % (loc.desc, last)), rest * esize)
            else:
                for name, val, _ in e.fields:
                    off, ft = T.field(name)
                    self.put(loc.plus(off, "%s.%s" % (loc.desc, name)), val, ft)
            return
        if is_aggregate(T):
            src = self.loc(e)
            self.copy(loc, src, T.size)
            self.free_loc(src)
            return
        v = self.val(e)
        self.store(loc, v)
        self.release(v)

    # -- conditions -------------------------------------------------------------------------------------

    def branch(self, e: Node, yes: str, no: str) -> None:
        """Jump to yes if the condition e holds, else to no.  Nothing stays in registers."""
        self.spill_all()
        if e.const is not None:
            self.emit("br", "=%s" % (yes if e.const else no), "%s is always %s" % (show(e), bool(e.const)))
            return
        if e.kind == "unary" and e.op == "not":
            self.branch(e.operand, no, yes)
            return
        if e.kind == "binary" and e.op in ("and", "or"):
            mid = self.label()
            if e.op == "and":
                self.branch(e.left, mid, no)
            else:
                self.branch(e.left, yes, mid)
            self.place(mid, "%s the right side: %s" % (e.op, show(e.right)))
            self.branch(e.right, yes, no)
            return
        if e.kind == "binary" and e.op in ("eq", "ne", "lt", "le", "gt", "ge"):
            cond = self.compare(e)
            self.emit("br.%s" % cond, "=%s" % yes, "if %s" % show(e))
            self.emit("br", "=%s" % no, "otherwise")
            return
        v = self.val(e)                       # a bool value
        self.emit("cmp", "%s, #1" % v.r(0), "%s is true?" % show(e))
        self.release(v)
        self.emit("br.eq", "=%s" % yes, "if %s" % show(e))
        self.emit("br", "=%s" % no, "otherwise")

    def compare(self, e: Node) -> str:
        """Set the flags for the comparison e; returns the condition suffix."""
        t = e.cmp_ty.resolved()
        n = t.size if not isinstance(t, NullT) else 2
        signed = isinstance(t, IntT) and t.signed
        op = e.op
        if op in ("eq", "ne"):
            left, right = e.left, e.right
            if self.cval(left) is not None and self.cval(right) is None:
                left, right = right, left
            a = self.val(left)
            b = self.operand(right)
            self.ensure(a)
            self.pin(a)
            if n == 1:
                self.emit("cmp", "%s, %s" % (a.r(0), self.src(b, 0)), "flags = %s - %s" % (a.desc, self.bdesc(b)))
            else:
                for k in range(n):
                    if not isinstance(b, Temp) and b[k] == 0:
                        continue                    # x eor 0 = x
                    self.emit("eor", "%s, %s, %s" % (a.r(k), a.r(k), self.src(b, k)),
                              "byte %d: 0 where %s and %s agree" % (k, a.desc, self.bdesc(b)))
                for k in range(1, n - 1):
                    self.emit("or", "%s, %s, %s" % (a.r(0), a.r(0), a.r(k)), "collect the differences")
                self.emit("ord", "%s, %s" % (a.r(0), a.r(n - 1)), "Z = all bytes equal")
            self.unpin(a)
            self.release(a)
            if isinstance(b, Temp):
                self.unpin(b)
                self.release(b)
            return op
        first, second = (e.left, e.right) if op in ("lt", "ge") else (e.right, e.left)
        a = self.val(first)
        b = self.operand(second)
        self.ensure(a)
        self.pin(a)
        what = "%s - %s" % (a.desc, self.bdesc(b))
        self.emit("cmp", "%s, %s" % (a.r(0), self.src(b, 0)), "flags = %s, byte 0" % what)
        for k in range(1, n):
            self.emit("subcd", "%s, %s" % (a.r(k), self.src(b, k)), "... byte %d with borrow" % k)
        self.unpin(a)
        self.release(a)
        if isinstance(b, Temp):
            self.unpin(b)
            self.release(b)
        if op in ("lt", "gt"):
            return "ss" if signed else "su"
        return "ges" if signed else "geu"

    def operand(self, e: Node):
        """A constant (list of bytes) or a pinned temp in registers."""
        c = self.cval(e)
        if c is not None:
            return le_bytes(c, size_of(e))
        t = self.val(e)
        self.pin(t)
        self.ensure(t)
        return t

    def src(self, b, k: int) -> str:
        if isinstance(b, Temp):
            return b.r(k)
        return "#%d" % b[k]

    def bdesc(self, b) -> str:
        if isinstance(b, Temp):
            return b.desc
        return str(int.from_bytes(bytes(b), "little"))

    # -- values -------------------------------------------------------------------------------------------

    def cval(self, e: Node) -> int | None:
        if e.const is None or e.ty is None:
            return None
        T = (getattr(e, "conv", None) or e.ty).resolved()
        if isinstance(T, (IntT, BoolT, NullT, PtrT, ManyT)):
            return e.const
        return None

    def val(self, e: Node) -> Temp:
        """A scalar value in a temp (in registers when returned)."""
        c = self.cval(e)
        if c is not None:
            return self.const(c, size_of(e), show(e))
        t = getattr(self, "v_" + e.kind)(e)
        t.desc = show(e)
        return self.ensure(t)

    def v_name(self, e: Node) -> Temp:
        return self.load(e.sym.loc, e.ty.resolved().size, e.name)

    def v_index(self, e: Node) -> Temp:
        loc = self.loc(e, once=True)
        t = self.load(loc, e.ty.resolved().size, show(e))
        self.free_loc(loc)
        return t

    v_field = v_index
    v_deref = v_index

    def v_sstr(self, e: Node) -> Temp:
        label = self.m.string_label(e.data)
        t = self.temp(2, show(e))
        self.emit("mova", "r10a, =%s" % label, "r10a = address of %s" % show(e))
        self.emit("mov", "%s, r10" % t.r(0))
        self.emit("mov", "%s, r11" % t.r(1))
        return t

    def v_ptr(self, e: Node) -> Temp:
        x = e.operand
        if x.kind == "name" and x.sym.kind == "func":
            x.sym.addressed = True
            t = self.temp(2, show(e))
            self.emit("mova", "r10a, =%s" % x.sym.name, "r10a = address of function %s" % x.sym.name)
            self.emit("mov", "%s, r10" % t.r(0))
            self.emit("mov", "%s, r11" % t.r(1))
            return t
        return self.addr_of(self.loc(x))

    def v_call(self, e: Node) -> Temp:
        return self.call(e)

    def v_boolof(self, e: Node) -> Temp:
        self.spill_all()
        t = Temp(1, show(e))
        t.slot = self.slot(1, "value of %s" % show(e, 30))
        yes, no, end = self.label(), self.label(), self.label()
        self.branch(e.operand, yes, no)
        for lab, v in ((yes, 1), (no, 0)):
            self.place(lab, "%s is %s" % (show(e.operand, 30), "true" if v else "false"))
            self.emit("mov", "r0, #%d" % v)
            self.byte_op("str", "r0", t.slot, 0, "%s = %s" % (show(e, 30), "true" if v else "false"))
            if v:
                self.emit("br", "=%s" % end)
        self.place(end)
        return t

    def v_unary(self, e: Node) -> Temp:
        t = self.val(e.operand)
        n = t.size
        if isinstance(e.ty.resolved(), BoolT):
            self.emit("eor", "%s, %s, #1" % (t.r(0), t.r(0)), "flip the bool")
            return t
        for k in range(n):
            self.emit("eor", "%s, %s, #255" % (t.r(k), t.r(k)), "invert %s" % byte_desc(t.desc, k, n))
        if e.op == "-":
            self.add_chain(t, [1] + [0] * (n - 1), False, "+ 1: two's complement negation")
        return t

    def add_chain(self, t: Temp, b, sub: bool, what: str) -> None:
        n = t.size
        base = "sub" if sub else "add"
        for k in range(n):
            if n == 1:
                ins, note = base, what
            elif k == 0:
                ins, note = base + "s", "%s, byte 0" % what
            elif k < n - 1:
                ins, note = base + "cs", "... byte %d with %s" % (k, "borrow" if sub else "carry")
            else:
                ins, note = base + "c", "... byte %d with %s" % (k, "borrow" if sub else "carry")
            self.emit(ins, "%s, %s, %s" % (t.r(k), t.r(k), self.src(b, k)), note)

    def v_binary(self, e: Node) -> Temp:
        if e.op in ("shl", "shr", "sar", "rol", "ror"):
            return self.shift(e)
        left, right = e.left, e.right
        if e.op in ("+", "*", "&", "|", "^") and self.cval(left) is not None and self.cval(right) is None:
            left, right = right, left               # the constant becomes an immediate
        return self.binop(e.op, self.val(left), right, e.ty, show(e))

    def binop(self, op: str, left: Temp, right: Node, ty: Type, what: str) -> Temp:
        """left op right, in place in left's registers (consumes left)."""
        T = ty.resolved()
        if op in ("*", "/", "%"):
            c = self.cval(right)
            if c is not None:
                t = self.const_op(op, left, c, T, what)
                if t is not None:
                    return t
            return self.call_helper(op, T, left, right, what)
        b = self.operand(right)
        self.ensure(left)
        self.pin(left)
        if op in ("+", "-"):
            self.add_chain(left, b, op == "-", what)
        else:
            ins = {"&": "and", "|": "or", "^": "eor"}[op]
            for k in range(left.size):
                self.emit(ins, "%s, %s, %s" % (left.r(k), left.r(k), self.src(b, k)), byte_desc(what, k, left.size))
        self.unpin(left)
        if isinstance(b, Temp):
            self.unpin(b)
            self.release(b)
        return left

    def shift(self, e: Node) -> Temp:
        T = e.ty.resolved()
        n = T.size
        w = 8 * n
        v = self.val(e.left)
        c = self.cval(e.right)
        what = show(e)
        if c is not None:
            if e.op in ("rol", "ror"):
                c %= w
            else:
                c = min(c, w)
            if c == 0:
                return v
            if c * n <= 24:
                for i in range(c):
                    self.shift1(e.op, v, "%s: step %d of %d" % (what, i + 1, c))
                return v
            self.pin(v)
            cnt = self.const(c, 1, "shift count")
            self.unpin(v)
        else:
            cnt = self.val(e.right)                 # v may be spilled meanwhile
            c0 = cnt.r(0)
            if e.op in ("rol", "ror"):
                self.emit("and", "%s, %s, #%d" % (c0, c0, w - 1), "rotate by the count modulo %d" % w)
            else:
                for k in range(1, cnt.size):
                    self.emit("cmp", "%s, #0" % cnt.r(k), "count >= 256?")
                    self.emit("mov.ne", "%s, #%d" % (c0, w), "then shift %d times" % w)
                self.emit("cmp", "%s, #%d" % (c0, w), "count > %d?" % w)
                self.emit("mov.gu", "%s, #%d" % (c0, w), "then shift %d times: all bits out" % w)
        self.pin(cnt)
        self.ensure(v)
        self.pin(v)
        top, done = self.label(), self.label()
        self.place(top, "shift loop: %s" % what)
        self.emit("cmp", "%s, #0" % cnt.r(0), "count left?")
        self.emit("br.eq", "=%s" % done, "no: done")
        self.shift1(e.op, v, "%s by one bit" % e.op)
        self.emit("sub", "%s, %s, #1" % (cnt.r(0), cnt.r(0)), "count - 1")
        self.emit("br", "=%s" % top)
        self.place(done)
        self.unpin(v, cnt)
        self.release(cnt)
        return v

    def shift1(self, op: str, v: Temp, what: str) -> None:
        n = v.size
        r = [v.r(k) for k in range(n)]
        if op == "shl":
            for k in range(n):
                ins = "lsl" if k == 0 and n == 1 else ("lsls" if k == 0 else ("csls" if k < n - 1 else "csl"))
                self.emit(ins, "%s, %s" % (r[k], r[k]), what if k == 0 else "... carry into byte %d" % k)
        elif op in ("shr", "sar"):
            first = "lsr" if op == "shr" else "asr"
            for i, k in enumerate(range(n - 1, -1, -1)):
                if i == 0:
                    ins = first if n == 1 else first + "s"
                else:
                    ins = "csrs" if k > 0 else "csr"
                self.emit(ins, "%s, %s" % (r[k], r[k]), what if i == 0 else "... carry into byte %d" % k)
        elif op == "rol":
            self.emit("lsld", r[n - 1], "%s: C = the top bit" % what)
            for k in range(n):
                self.emit("csls" if k < n - 1 else "csl", "%s, %s" % (r[k], r[k]), "... rotate byte %d" % k)
        else:
            self.emit("lsrd", r[0], "%s: C = the low bit" % what)
            for k in range(n - 1, -1, -1):
                self.emit("csrs" if k > 0 else "csr", "%s, %s" % (r[k], r[k]), "... rotate byte %d" % k)

    def v_cast(self, e: Node) -> Temp:
        S = e.operand.ty.resolved()
        D = e.ty.resolved()
        x = e.operand
        if not isinstance(D, BoolT) and D.size < size_of(x) and self.cval(x) is None:
            # narrowing: only the low bytes (little-endian: the first ones) are loaded
            if x.kind in ("name", "index", "field", "deref") and self.m.is_lvalue(x):
                loc = self.loc(x)
                t = self.load(loc, D.size, show(e))
                self.free_loc(loc)
                return t
            if x.kind == "call" and not is_aggregate(x.ty):
                return self.call(x, want=D.size)
        t = self.val(e.operand)
        if isinstance(D, BoolT):
            if isinstance(S, BoolT):
                return t
            n = t.size
            for k in range(1, n - 1):
                self.emit("or", "%s, %s, %s" % (t.r(0), t.r(0), t.r(k)), "collect the bits of %s" % t.desc)
            self.emit("ord", "%s, %s" % (t.r(0), t.r(n - 1) if n > 1 else "#0"), "Z = (%s is 0)" % t.desc)
            self.emit("mov.ne", "%s, #1" % t.r(0), "not 0: true")
            self.resize(t, 1)
            return t
        if D.size < t.size:
            self.resize(t, D.size)
        elif D.size > t.size:
            self.extend(t, D.size, isinstance(S, IntT) and S.signed)
        return t

    def v_as(self, e: Node) -> Temp:
        D = e.ty.resolved()
        x = e.operand
        if (size_of(x) != D.size and self.m.is_lvalue(x)) or is_aggregate(x.ty):
            loc = self.loc(x)
            t = self.load(loc, D.size)
            self.free_loc(loc)
            return t
        t = self.val(x)
        if D.size < t.size:
            self.resize(t, D.size)
        elif D.size > t.size:
            self.extend(t, D.size, False)
        return t

    # -- locations --------------------------------------------------------------------------------------

    def loc(self, e: Node, once: bool = False):
        """The memory of an lvalue or an aggregate value.  once: it is
        accessed once, right away, so a pointer variable can be read then."""
        k = e.kind
        if k == "name":
            if e.sym.kind != "var":
                raise YError("'%s' is not a variable" % e.name, e.where)
            return e.sym.loc
        if k == "deref":
            return PtrLoc(self.val(e.ptr), 0, show(e))
        if k == "field":
            return self.loc(e.obj, once).plus(e.offset, show(e))
        if k == "index":
            ot = e.obj.ty.resolved()
            esize = e.ty.resolved().size
            if isinstance(ot, ArrayT):
                base = self.loc(e.obj, once)
                if isinstance(base, (GlobalLoc, StackLoc, SpLoc)) and self.cval(e.index) is None:
                    base = PtrLoc(None, 0, show(e.obj), base=("addr", base))
            elif once and e.obj.kind == "name" and isinstance(e.obj.sym.loc, GlobalLoc) and not has_call(e.index):
                base = PtrLoc(None, 0, show(e.obj), base=("mem", e.obj.sym.loc))
            else:
                base = PtrLoc(self.val(e.obj), 0, show(e.obj))
            c = self.cval(e.index)
            if c is not None:
                return base.plus(c * esize, show(e))
            if base.index is None:
                # base + index: `ldo / sto rX, r10a, rIa`, or `lea r10a, r10a, rIa` first
                i = self.val(e.index)
                self.extend(i, 2, e.index.ty.resolved().signed)
                self.scale(i, esize)
                i.desc = show(e.index)
                return PtrLoc(base.temp, base.off, show(e), index=i, base=base.base)
            a = self.addr_of(base)
            i = self.val(e.index)
            self.extend(i, 2, e.index.ty.resolved().signed)
            self.scale(i, esize)
            self.pin(i)
            self.ensure(a)
            self.unpin(i)
            self.emit("adds", "%s, %s, %s" % (a.r(0), a.r(0), i.r(0)), "address of %s" % show(e))
            self.emit("addc", "%s, %s, %s" % (a.r(1), a.r(1), i.r(1)))
            self.release(i)
            a.desc = "@ptr(%s)" % show(e)
            return PtrLoc(a, 0, show(e))
        if k == "str":
            return GlobalLoc(self.m.string_label(e.data), 0, show(e))
        if k == "call":
            return self.call(e)
        if k == "as":
            x = e.operand
            if self.m.is_lvalue(x) or is_aggregate(x.ty):
                return self.loc(x)
            v = self.val(x)
            loc = self.slot(max(v.size, e.ty.resolved().size), "scratch: %s" % show(e, 30))
            self.store(loc, v)
            self.release(v)
            return loc
        if k == "init":
            loc = self.slot(e.ty.resolved().size, "scratch: initialiser")
            self.put(loc, e, e.ty)
            return loc
        raise YError("this expression has no memory location", e.where)

    def scale(self, i: Temp, size: int) -> None:
        """i (2 bytes, in registers) *= size, by shifts and adds."""
        if size == 1:
            return
        if size & (size - 1) == 0:
            for _ in range(size.bit_length() - 1):
                self.emit("lsls", "%s, %s" % (i.r(0), i.r(0)), "index * 2 (element size %d)" % size)
                self.emit("csl", "%s, %s" % (i.r(1), i.r(1)))
            return
        self.pin(i)
        acc = self.const(0, 2, "index * %d" % size)
        self.unpin(i)
        bit = 1
        while bit <= size:
            if size & bit:
                self.emit("adds", "%s, %s, %s" % (acc.r(0), acc.r(0), i.r(0)), "+ index * %d" % bit)
                self.emit("addc", "%s, %s, %s" % (acc.r(1), acc.r(1), i.r(1)))
            bit <<= 1
            if bit <= size:
                self.emit("lsls", "%s, %s" % (i.r(0), i.r(0)), "index * %d" % bit)
                self.emit("csl", "%s, %s" % (i.r(1), i.r(1)))
        for k in range(2):
            self.emit("mov", "%s, %s" % (i.r(k), acc.r(k)), "index * %d (element size)" % size if k == 0 else "")
        self.release(acc)

    # -- calls (ABI 0.3) --------------------------------------------------------------------------------

    def call(self, e: Node, want: int | None = None):
        """A call; with want, only the low want bytes of a scalar result are loaded."""
        fnty = e.fnty
        target = e.direct
        if target is None:
            fp = self.val(e.func)
            res = self.emit_call(fp, self.eval_args(e.args, fnty.params), fnty, show(e))
            if want is not None and isinstance(res, Temp) and res.size > want:
                self.resize(res, want)
            return res
        target.called = True
        if target.recursive:
            return self.call_direct_stack(target, e.args, fnty, show(e), want)
        return self.call_direct_static(target, e.args, fnty, show(e), want)

    def eval_args(self, args: list[Node], params: list[Type]) -> list:
        """Arguments as temps, or scratch slots holding aggregates."""
        out = []
        for a, p in zip(args, params):
            if is_aggregate(p):
                scratch = self.slot(p.resolved().size, "scratch: argument %s" % show(a, 30))
                self.put(scratch, a, p)
                out.append(scratch)
            else:
                out.append(self.val(a))
        return out

    def call_direct_static(self, g: Sym, args: list[Node], fnty: FnT, what: str, want: int | None):
        """Call g (not @recursive).  Each argument is written into g.frame as
        soon as it is computed, except those before the last argument that
        calls something (that call could be g itself): they wait in temps."""
        ret = fnty.ret
        R = ret.resolved().size if ret else 0
        frame = GlobalLoc(g.name + ".frame", 0, g.name + ".frame")
        last = max((i for i, a in enumerate(args) if has_call(a)), default=-1)
        early = self.eval_args(args[:last + 1], fnty.params[:last + 1])
        off = R
        for i, (a, p) in enumerate(zip(args, fnty.params)):
            size = p.resolved().size
            dst = frame.plus(off, "argument %d of %s" % (i + 1, g.name))
            if i <= last:
                if isinstance(early[i], Temp):
                    self.store(dst, early[i])
                    self.release(early[i])
                else:
                    self.copy(dst, early[i], size)
            else:
                self.put(dst, a, p)
            off += size
        self.spill_all()
        self.emit("brl", "r12a, =%s" % g.name, "call %s" % what)
        if not R:
            return None
        res_loc = frame.plus(0, "result of %s" % g.name)
        if is_aggregate(ret):
            result = self.slot(R, "scratch: result of %s" % show_name(what))
            self.copy(result, res_loc, R)
            return result
        return self.load(res_loc, min(R, want or R), what)

    def call_direct_stack(self, g: Sym, args: list[Node], fnty: FnT, what: str, want: int | None):
        """Call g (@recursive): room for the result and the arguments below SP
        first, then each argument straight into it.  Calls made while
        computing an argument use the stack below, so they cannot disturb it."""
        ret = fnty.ret
        R = ret.resolved().size if ret else 0
        A = R + sum(p.resolved().size for p in fnty.params)
        if A:
            self.emit("lea", "r14a, r14a, #%d" % -A, "SP -= %d: result and arguments of %s" % (A, g.name))
            self.sp_delta += A
        delta = self.sp_delta
        off = R
        for i, (a, p) in enumerate(zip(args, fnty.params)):
            self.put(SpLoc(off, delta, "argument %d of %s" % (i + 1, g.name)), a, p)
            off += p.resolved().size
        self.spill_all()
        self.emit("brl", "r12a, =%s" % g.name, "call %s" % what)
        result = None
        if R:
            res_loc = SpLoc(0, delta, "result of %s" % g.name)
            if is_aggregate(ret):
                result = self.slot(R, "scratch: result of %s" % show_name(what))
                self.copy(result, res_loc, R)
            else:
                result = self.load(res_loc, min(R, want or R), what)
        if A:
            self.emit("lea", "r14a, r14a, #%d" % A, "SP += %d" % A)
            self.sp_delta -= A
        return result

    def call_helper(self, op: str, T: IntT, left: Temp, right: Node, what: str) -> Temp:
        """left op right through a helper routine: the operands go straight
        into its frame (left first, unless right calls something itself)."""
        fn = self.m.helper(op, T)
        n = T.size
        frame = GlobalLoc(fn.name + ".frame", 0, fn.name + ".frame")
        a, b = frame.plus(n, "a of %s" % fn.name), frame.plus(2 * n, "b of %s" % fn.name)
        if has_call(right):
            r = self.val(right)
            self.store(a, left)
            self.store(b, r)
            self.release(r)
        else:
            self.store(a, left)
            self.release(left)
            left = None
            r = self.val(right)
            self.store(b, r)
            self.release(r)
        if left is not None:
            self.release(left)
        self.spill_all()
        self.emit("brl", "r12a, =%s" % fn.name, "call %s" % what)
        res = prelude.result_offset(op, T.bits)
        return self.load(frame.plus(res, "%s of %s" % ("a % b" if res else ("a / b" if op != "*" else "a * b"),
                                                       fn.name)), n, what)

    def const_op(self, op: str, left: Temp, c: int, T: IntT, what: str) -> Temp | None:
        """left * c, left / c, left % c without a helper, or None."""
        n = T.size
        c &= (1 << T.bits) - 1
        if op == "*":
            if c == 0:
                self.release(left)
                return self.const(0, n, what)
            bits = [i for i in range(T.bits) if c >> i & 1]
            if len(bits) == 1:
                if bits[0] * n > 24:
                    return None
                self.ensure(left)
                for i in range(bits[0]):
                    self.shift1("shl", left, "%s: * 2" % what)
                return left
            cost = n * (bits[-1] + len(bits))
            if cost > 16:
                return None
            self.ensure(left)
            self.pin(left)
            acc = None
            for i in range(bits[-1] + 1):
                if c >> i & 1:
                    if acc is None:
                        acc = self.temp(n, what)
                        for k in range(n):
                            self.emit("mov", "%s, %s" % (acc.r(k), left.r(k)), "%s: %s * %d" % (what, left.desc, 1 << i)
                                      if k == 0 else "")
                    else:
                        self.add_chain(acc, left, False, "+ %s * %d" % (left.desc, 1 << i))
                if i < bits[-1]:
                    self.shift1("shl", left, "%s * %d" % (left.desc, 2 << i))
            self.unpin(left)
            self.release(left)
            return acc
        if T.signed or c == 0 or c & (c - 1):
            return None                         # signed, or not a power of 2: the helper
        k = c.bit_length() - 1
        if op == "/":
            if k * n > 24:
                return None
            self.ensure(left)
            for i in range(k):
                self.shift1("shr", left, "%s: / 2" % what)
            return left
        self.ensure(left)                       # % 2^k: keep the low k bits
        for b, m in enumerate(le_bytes(c - 1, n)):
            if m == 0:
                self.emit("mov", "%s, #0" % left.r(b), "%s, byte %d" % (what, b))
            elif m != 255:
                self.emit("and", "%s, %s, #%d" % (left.r(b), left.r(b), m), "%s, byte %d" % (what, b))
        return left

    def emit_call(self, target: Temp, args: list, fnty: FnT, what: str):
        """Call through the function pointer in target with the evaluated
        arguments (temps, or frame locations of aggregates)."""
        ret = fnty.ret
        R = ret.resolved().size if ret else 0
        aggregate = ret is not None and is_aggregate(ret)
        # the header before the function says which convention
        fp = target
        self.ensure(fp)
        self.pin(fp)
        hf = self.temp(2, "frame of %s" % fp.desc)
        self.unpin(fp)
        self.code.append("; call through a pointer: the header at the function - 4 holds its static frame, "
                         "or 0 for a @recursive function")
        self.emit("mov", "r10, %s" % fp.r(0), "r10a = the function in %s" % fp.regs_text())
        self.emit("mov", "r11, %s" % fp.r(1))
        self.emit("ldo", "%s, r10a, #-4" % hf.r(0), "its static frame (header), low")
        self.emit("ldo", "%s, r10a, #-3" % hf.r(1), "... high")
        self.emit("ord", "%s, %s" % (hf.r(0), hf.r(1)), "0: @recursive, arguments on the stack")
        self.spill_all()
        stack_path, done = self.label(), self.label()
        self.emit("br.eq", "=%s" % stack_path)
        result = None
        if R:
            result = self.slot(R, "scratch: result of %s" % show_name(what))
        res = self.call_static(PtrLoc(hf, 0, "frame of the function"), None, fp, args, fnty, what)
        self.keep_result(res, result, R, aggregate)
        self.spill_all()
        self.emit("br", "=%s" % done)
        self.place(stack_path, "the function is @recursive")
        res = self.call_stack(None, fp, args, fnty, what)
        self.keep_result(res, result, R, aggregate)
        self.spill_all()
        self.place(done)
        for a in args:
            if isinstance(a, Temp):
                self.release(a)
        self.release(hf)
        self.release(fp)
        if not R:
            return None
        if aggregate:
            return result
        t = Temp(R, what)
        t.slot = result
        return t

    def keep_result(self, res, slot, R: int, aggregate: bool) -> None:
        """Put the result of one path of a call through a pointer into slot."""
        if not R:
            return
        if aggregate:
            self.copy(slot, res, R)
        else:
            self.store(slot, res)
            self.release(res)

    def call_static(self, frame, name: str | None, fp: Temp | None, args: list, fnty: FnT, what: str):
        """Call a non-recursive function: the arguments go into its frame."""
        ret = fnty.ret
        R = ret.resolved().size if ret else 0
        self.spill_all()
        off = R
        for i, (arg, p) in enumerate(zip(args, fnty.params)):
            size = p.resolved().size
            dst = frame.plus(off, "argument %d of %s" % (i + 1, name or "the call"))
            if isinstance(arg, Temp):
                self.store(dst, arg)
            else:
                self.copy(dst, arg, size)
            off += size
        self.forget_reloads()
        self.brl(name, fp, what)
        if not R:
            return None
        res_loc = frame.plus(0, "result of %s" % (name or "the call"))
        if is_aggregate(ret):
            result = self.slot(R, "scratch: result of %s" % show_name(what))
            self.copy(result, res_loc, R)
            return result
        return self.load(res_loc, R, what)

    def call_stack(self, name: str | None, fp: Temp | None, args: list, fnty: FnT, what: str):
        """Call a @recursive function: result and arguments below SP."""
        ret = fnty.ret
        R = ret.resolved().size if ret else 0
        A = R + sum(p.resolved().size for p in fnty.params)
        self.spill_all()
        if A:
            self.emit("lea", "r14a, r14a, #%d" % -A, "SP -= %d: result and arguments of %s" % (A, name or "the call"))
            self.sp_delta += A
        delta = self.sp_delta
        off = R
        for i, (arg, p) in enumerate(zip(args, fnty.params)):
            size = p.resolved().size
            dst = SpLoc(off, delta, "argument %d of %s" % (i + 1, name or "the call"))
            if isinstance(arg, Temp):
                self.store(dst, arg)
            else:
                self.copy(dst, arg, size)
            off += size
        self.forget_reloads()
        self.brl(name, fp, what)
        result = None
        if R:
            res_loc = SpLoc(0, delta, "result of %s" % (name or "the call"))
            if is_aggregate(ret):
                result = self.slot(R, "scratch: result of %s" % show_name(what))
                self.copy(result, res_loc, R)
            else:
                result = self.load(res_loc, R, what)
        if A:
            self.emit("lea", "r14a, r14a, #%d" % A, "SP += %d" % A)
            self.sp_delta -= A
        return result

    def brl(self, name: str | None, fp: Temp | None, what: str) -> None:
        if fp is None:
            self.emit("brl", "r12a, =%s" % name, "call %s" % what)
            return
        self.spill_all()                     # everything in memory, fp included
        self.ensure(fp)
        self.emit("mov", "r10, %s" % fp.r(0), "r10a = the function")
        self.emit("mov", "r11, %s" % fp.r(1))
        self.free.update(fp.regs)            # its value stays in its spill slot
        self.live.remove(fp)
        fp.regs = None
        self.emit("brl", "r12a, r10a", "call %s" % what)

def has_call(e) -> bool:
    """Whether evaluating e may call a function (or a helper of * / %)."""
    if isinstance(e, Node):
        if e.kind == "call" or (e.kind == "binary" and e.op in ("*", "/", "%")):
            return True
        return any(has_call(v) for k, v in e.__dict__.items() if k not in ("ty", "const", "conv", "cmp_ty", "fnty"))
    if isinstance(e, (list, tuple)):
        return any(has_call(x) for x in e)
    return False


def show_name(what: str) -> str:
    return what if len(what) <= 30 else what[:27] + "..."


def size_of(e: Node) -> int:
    t = getattr(e, "conv", None) or e.ty
    t = t.resolved()
    if isinstance(t, NullT):
        return 2
    return t.size
