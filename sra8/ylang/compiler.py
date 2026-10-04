"""Type checker and code generator of ylangc 0.1.

Deliberately simple (docs/ylangc.md):

* Every variable lives in memory: globals at their label, locals and
  parameters in the stack frame.  Nothing is kept in a register across
  statements.
* While an expression is computed, intermediate values ("temps") stay in
  r0 ... r9.  When those run out, the oldest temp is written to a spill
  slot in the frame and loaded again when it is needed.
* Before every call and every branch inside an expression, all temps are
  written to their spill slots, so every label is reached with nothing in
  registers.
* r10a is the address register, r12a the link register, r14a the stack
  pointer.

ABI 0.1 (docs/ylangc.md): the stack grows down, SP points at the next free
byte.  The caller reserves room for the result and the arguments below
its frame, writes the arguments, calls with `brl r12a`, reads the result
and frees the room.  Every register may be changed by a call.
"""

from __future__ import annotations

from .ast import Node
from .errors import YError
from . import prelude
from .types import (BOOL, COND, INT16, NULL, OPAQUE, UINT8, UINT16, ArrayT, BoolT, CondT, FnT, IntT,
                    ManyT, NamedT, NullT, OpaqueT, PtrT, StructT, Type, BUILTIN_TYPES, implicit,
                    is_aggregate, is_int, is_ptr, same)


class VoidT(Type):
    complete = False

    def __str__(self) -> str:
        return "nothing"


VOID = VoidT()
REGS = list(range(10))              # r0 ... r9 hold temps


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
        self.loc = None               # GlobalLoc or FrameLoc for variables
        self.helper = False


# ---------------------------------------------------------------------------------------------
# locations and temps (code generation)
# ---------------------------------------------------------------------------------------------

class Slot:
    """Bytes of the frame.  kind: 'local' (base fixed at the end), 'lr',
    or 'caller' (the caller's result and argument area, at frame size + off)."""

    def __init__(self, size: int, kind: str = "local", off: int = 0) -> None:
        self.size, self.kind, self.off = size, kind, off
        self.base = 0


class GlobalLoc:
    def __init__(self, label: str, off: int = 0) -> None:
        self.label, self.off = label, off

    def plus(self, n: int) -> "GlobalLoc":
        return GlobalLoc(self.label, self.off + n)


class FrameLoc:
    def __init__(self, slot: Slot, off: int = 0) -> None:
        self.slot, self.off = slot, off

    def plus(self, n: int) -> "FrameLoc":
        return FrameLoc(self.slot, self.off + n)


class SpLoc:
    """The outgoing area of a call: byte `off` above SP as it was when
    the stack depth was `delta`."""

    def __init__(self, off: int, delta: int) -> None:
        self.off, self.delta = off, delta

    def plus(self, n: int) -> "SpLoc":
        return SpLoc(self.off + n, self.delta)


class PtrLoc:
    """Memory at the address held by a temp, plus off."""

    def __init__(self, temp: "Temp", off: int = 0) -> None:
        self.temp, self.off = temp, off

    def plus(self, n: int) -> "PtrLoc":
        return PtrLoc(self.temp, self.off + n)


class Temp:
    def __init__(self, size: int) -> None:
        self.size = size
        self.regs: list[int] | None = None
        self.slot: Slot | None = None
        self.pinned = 0
        self.dead = False

    def r(self, k: int) -> str:
        assert self.regs is not None, "temp not in registers"
        return "r%d" % self.regs[k]


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
                sym.loc = GlobalLoc(d.name)
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

    def define(self, kind: str, name: str, ty: Type, where: tuple[str, int], internal: bool) -> Sym:
        old = self.find(name)
        if old is not None:
            if not old.declared or old.defined or old.kind != kind:
                raise YError("'%s' is already declared (at %s:%d)" % (name, old.where[0], old.where[1]), where)
            if not same(old.ty, ty):
                raise YError("'%s' is defined as %s but declared as %s" % (name, ty, old.ty), where)
            sym = old
        else:
            sym = Sym(kind, name, ty, where)
            self.scopes[0][name] = sym
        sym.defined = True
        sym.internal = internal
        return sym

    def top_impl(self, d: Node, helper: bool = False) -> None:
        params = [self.resolve(t) for _, t, _ in d.params]
        ret = self.resolve(d.ret) if d.ret else None
        fnty = FnT(params, ret, [n for n, _, _ in d.params])
        sym = self.define("func", d.name, fnty, d.where, d.internal)
        sym.helper = helper
        if d.main:
            if self.main is not None:
                raise YError("only one @main per file", d.where)
            if params or ret is not None:
                raise YError("the @main function takes no parameters and returns nothing (ABI 0.1)", d.where)
            self.main = sym
        for p in params + ([ret] if ret else []):
            if not p.resolved().complete:
                raise YError("parameters and results need complete types, not %s" % p, d.where)
        gen = FuncGen(self, d, sym, fnty)
        self.fn = gen
        lines = gen.run()
        self.fn = None
        self.code_sections.append((d.section, lines))

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
        if d.value is None:
            self.bss.append("%s:" % d.name)
            self.bss.append("        .res %d" % t.resolved().size)
        else:
            items: list = []
            self.static_value(d.value, t, items)
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
        if not self.helpers_used:
            return
        from .lexer import tokenize
        from .parser import parse
        need = set(self.helpers_used)
        for n in list(need):
            if n.startswith("__divs"):
                need.add("__divu" + n[6:])
            if n.startswith("__mods"):
                need.add("__modu" + n[6:])
        items = parse(tokenize([("<ylangc helpers>", i + 1, t) for i, t in enumerate(prelude.source().split("\n"))]))
        user_scopes = self.scopes
        self.scopes = [{}]                      # the helpers see only each other
        try:
            for item in items:
                if item.name in need:
                    self.top_impl(item, helper=True)
        finally:
            self.scopes = user_scopes

    def helper(self, op: str, t: IntT) -> Sym:
        name = prelude.helper_name(op, t.bits, t.signed)
        self.helpers_used.add(name)
        sym = Sym("func", name, FnT([t, t], t), ("<ylangc helpers>", 0))
        return sym

    # -- output --------------------------------------------------------------------------------------

    def output(self) -> str:
        g = self.scopes[0]
        imports = sorted(s.name for s in g.values()
                         if s.kind in ("var", "func") and s.declared and not s.defined and s.used)
        exports = [s.name for s in g.values() if s.kind in ("var", "func") and s.defined and not s.internal]
        out = ["; generated by ylangc 0.1", ""]
        if self.main is not None:
            imports.append("__stack_top")
        for name in imports:
            out.append("        .import %s" % name)
        for name in exports:
            out.append("        .export %s" % name)
        if self.main is not None:
            out += ["", "; start-up: the stack pointer, then the @main function (ABI 0.1)",
                    "        .code vector", "        .export _start",
                    "_start: mova    r14a, =__stack_top",
                    "        brl     r12a, =%s" % self.main.name,
                    ".l spin:",
                    "        br      .b =spin"]
        for section, lines in self.code_sections:
            out.append("")
            out.append("        .code %s" % section if section else "        .code")
            out.extend(lines)
        if self.data or self.strings:
            out += ["", "        .data"]
            out.extend(self.data)
            for label, data in self.strings:
                out.append("%s:" % label)
                out.extend(data_lines(data + [0]))
        if self.bss:
            out += ["", "        .bss"]
            out.extend(self.bss)
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

class FuncGen:
    def __init__(self, module: Module, d: Node, sym: Sym, fnty: FnT) -> None:
        self.m = module
        self.d = d
        self.sym = sym
        self.fnty = fnty
        self.code: list = []
        self.free = set(REGS)
        self.live: list[Temp] = []           # temps in registers, oldest first
        self.slots: list[Slot] = []
        self.pool: dict[int, list[Slot]] = {}
        self.sp_delta = 0
        self.nlabel = 0
        self.loops: list[tuple[str | None, str, str]] = []
        self.lr_slot = Slot(2, "lr")
        self.ret_label = self.label()
        R = fnty.ret.resolved().size if fnty.ret else 0
        self.ret_slot = Slot(R, "caller", 0) if R else None
        self.param_slots = []
        off = R
        for t in fnty.params:
            self.param_slots.append(Slot(t.resolved().size, "caller", off))
            off += t.resolved().size

    # -- emission -----------------------------------------------------------------------------------

    def emit(self, text: str) -> None:
        self.code.append("        " + text)

    def label(self) -> str:
        self.nlabel += 1
        return "%s.%d" % (self.sym.name, self.nlabel)

    def place(self, label: str) -> None:
        self.code.append("%s:" % label)

    def frame_addr(self, slot: Slot, k: int) -> None:
        """r10a <- address of byte k of the slot."""
        self.code.append(("fa", slot, k, self.sp_delta))

    def sp_addr(self, off: int) -> None:
        """r10a <- SP + off."""
        self.emit("adds    r10, r14, #%d" % lo(off))
        self.emit("addc    r11, r15, #%d" % hi(off))

    def sp_sub(self, n: int) -> None:
        self.emit("subs    r14, r14, #%d" % lo(n))
        self.emit("subc    r15, r15, #%d" % hi(n))

    def sp_add(self, n: int) -> None:
        self.emit("adds    r14, r14, #%d" % lo(n))
        self.emit("addc    r15, r15, #%d" % hi(n))

    # -- temps ----------------------------------------------------------------------------------------

    def new_slot(self, size: int) -> Slot:
        s = Slot(size)
        self.slots.append(s)
        return s

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

    def temp(self, size: int) -> Temp:
        t = Temp(size)
        t.regs = self.alloc(size)
        self.live.append(t)
        return t

    def spill(self, t: Temp) -> None:
        if t.regs is None:
            return
        if t.slot is None:
            t.slot = self.slot_for(t.size)
        for k in range(t.size):
            self.frame_addr(t.slot, k)
            self.emit("str     %s, r10a" % t.r(k))
        self.free.update(t.regs)
        t.regs = None
        self.live.remove(t)

    def slot_for(self, size: int) -> Slot:
        pool = self.pool.get(size)
        if pool:
            return pool.pop()
        return self.new_slot(size)

    def ensure(self, t: Temp) -> Temp:
        if t.regs is None:
            regs = self.alloc(t.size)
            for k, r in enumerate(regs):
                self.frame_addr(t.slot, k)
                self.emit("ldr     r%d, r10a" % r)
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

    def resize(self, t: Temp, size: int) -> None:
        """Drop high bytes (size < t.size); the caller extends otherwise."""
        assert t.regs is not None
        for r in t.regs[size:]:
            self.free.add(r)
        t.regs = t.regs[:size]
        t.size = size
        t.slot = None                      # the old slot has the wrong size; a new one when spilled

    def extend(self, t: Temp, size: int, signed: bool) -> None:
        assert t.regs is not None
        if size <= t.size:
            return
        self.pin(t)
        extra = self.alloc(size - t.size)
        self.unpin(t)
        top = t.r(t.size - 1)
        if signed:
            self.emit("mov     r%d, #0" % extra[0])
            self.emit("andd    %s, #128" % top)
            self.emit("mov.ne  r%d, #255" % extra[0])
            for r in extra[1:]:
                self.emit("mov     r%d, r%d" % (r, extra[0]))
        else:
            for r in extra:
                self.emit("mov     r%d, #0" % r)
        t.regs = t.regs + extra
        t.size = size
        t.slot = None

    def const(self, value: int, size: int) -> Temp:
        t = self.temp(size)
        for k, b in enumerate(le_bytes(value, size)):
            self.emit("mov     %s, #%d" % (t.r(k), b))
        return t

    # -- memory access ----------------------------------------------------------------------------------

    def byte_op(self, op: str, reg: str, loc, k: int) -> None:
        """ldr/str reg <-> byte k of loc.  A PtrLoc's temp must be in registers."""
        if isinstance(loc, GlobalLoc):
            off = loc.off + k
            self.emit("%-7s %s, =%s%s" % (op, reg, loc.label, "+%d" % off if off else ""))
            return
        if isinstance(loc, FrameLoc):
            self.frame_addr(loc.slot, loc.off + k)
        elif isinstance(loc, SpLoc):
            self.sp_addr(1 + loc.off + k + self.sp_delta - loc.delta)
        else:
            t = loc.temp
            off = loc.off + k
            self.emit("mov     r10, %s" % t.r(0))
            self.emit("mov     r11, %s" % t.r(1))
            if off:
                self.emit("adds    r10, r10, #%d" % lo(off))
                self.emit("addc    r11, r11, #%d" % hi(off))
        self.emit("%-7s %s, r10a" % (op, reg))

    def load(self, loc, size: int) -> Temp:
        if isinstance(loc, PtrLoc):
            self.ensure(loc.temp)
            self.pin(loc.temp)
        t = self.temp(size)
        for k in range(size):
            self.byte_op("ldr", t.r(k), loc, k)
        if isinstance(loc, PtrLoc):
            self.unpin(loc.temp)
        return t

    def store(self, loc, t: Temp) -> None:
        self.ensure(t)
        self.pin(t)
        if isinstance(loc, PtrLoc):
            self.ensure(loc.temp)
        self.unpin(t)
        for k in range(t.size):
            self.byte_op("str", t.r(k), loc, k)

    def free_loc(self, loc) -> None:
        if isinstance(loc, PtrLoc):
            self.release(loc.temp)

    def addr_of(self, loc, consume: bool = True) -> Temp:
        """The address of loc as a 2-byte temp.  A PtrLoc's temp is reused
        (consumed) unless consume is False."""
        if isinstance(loc, PtrLoc) and not consume:
            src = self.ensure(loc.temp)
            self.pin(src)
            t = self.temp(2)
            self.unpin(src)
            self.emit("mov     %s, %s" % (t.r(0), src.r(0)))
            self.emit("mov     %s, %s" % (t.r(1), src.r(1)))
            if loc.off:
                self.emit("adds    %s, %s, #%d" % (t.r(0), t.r(0), lo(loc.off)))
                self.emit("addc    %s, %s, #%d" % (t.r(1), t.r(1), hi(loc.off)))
            return t
        if isinstance(loc, PtrLoc):
            t = self.ensure(loc.temp)
            if loc.off:
                self.emit("adds    %s, %s, #%d" % (t.r(0), t.r(0), lo(loc.off)))
                self.emit("addc    %s, %s, #%d" % (t.r(1), t.r(1), hi(loc.off)))
            return t
        t = self.temp(2)
        if isinstance(loc, GlobalLoc):
            self.emit("mova    r10a, =%s%s" % (loc.label, "+%d" % loc.off if loc.off else ""))
        elif isinstance(loc, FrameLoc):
            self.frame_addr(loc.slot, loc.off)
        else:
            self.sp_addr(1 + loc.off + self.sp_delta - loc.delta)
        self.emit("mov     %s, r10" % t.r(0))
        self.emit("mov     %s, r11" % t.r(1))
        return t

    def copy(self, dst, src, size: int) -> None:
        """Copy size bytes, forward, one at a time (so an overlapping copy
        from lower addresses repeats a pattern)."""
        if size <= 0:
            return
        s = self.addr_of(src, consume=False)
        self.pin(s)
        d = self.addr_of(dst, consume=False)
        self.unpin(s)
        self.spill_all()
        for k, r in ((0, 2), (1, 3)):
            self.frame_addr(s.slot, k)
            self.emit("ldr     r%d, r10a" % r)
        for k, r in ((0, 4), (1, 5)):
            self.frame_addr(d.slot, k)
            self.emit("ldr     r%d, r10a" % r)
        self.release(s)
        self.release(d)
        self.emit("mov     r6, #%d" % lo(size))
        self.emit("mov     r7, #%d" % hi(size))
        top = self.label()
        self.place(top)
        self.emit("ldr     r0, r2a")
        self.emit("str     r0, r4a")
        self.emit("adds    r2, r2, #1")
        self.emit("addc    r3, r3, #0")
        self.emit("adds    r4, r4, #1")
        self.emit("addc    r5, r5, #0")
        self.emit("subs    r6, r6, #1")
        self.emit("subc    r7, r7, #0")
        self.emit("ord     r6, r7")
        self.emit("br.ne   =%s" % top)

    # -- the function -----------------------------------------------------------------------------------

    def run(self) -> list[str]:
        m = self.m
        m.scopes.append({})
        for (name, _, pw), t, slot in zip(self.d.params, self.fnty.params, self.param_slots):
            sym = Sym("var", name, t, pw)
            sym.loc = FrameLoc(slot)
            sym.defined = True
            m.declare(sym)
        self.block(self.d.body, new_scope=False)
        m.scopes.pop()
        return self.finish()

    def finish(self) -> list[str]:
        base = 0
        for s in self.slots:
            s.base = base
            base += s.size
        L = base
        self.lr_slot.base = L
        F = L + 2
        out = ["", "; %s: %s" % (self.sym.name, self.fnty), "%s:" % self.sym.name]

        def fa(slot: Slot, k: int, delta: int) -> list[str]:
            b = slot.base if slot.kind != "caller" else F + slot.off
            off = 1 + b + k + delta
            return ["        adds    r10, r14, #%d" % lo(off), "        addc    r11, r15, #%d" % hi(off)]

        out.append("        subs    r14, r14, #%d" % lo(F))
        out.append("        subc    r15, r15, #%d" % hi(F))
        out += fa(self.lr_slot, 0, 0) + ["        str     r12, r10a"]
        out += fa(self.lr_slot, 1, 0) + ["        str     r13, r10a"]
        for item in self.code:
            if isinstance(item, tuple):
                _, slot, k, delta = item
                out += fa(slot, k, delta)
            else:
                out.append(item)
        out.append("%s:" % self.ret_label)
        out += fa(self.lr_slot, 0, 0) + ["        ldr     r12, r10a"]
        out += fa(self.lr_slot, 1, 0) + ["        ldr     r13, r10a"]
        out.append("        adds    r14, r14, #%d" % lo(F))
        out.append("        addc    r15, r15, #%d" % hi(F))
        out.append("        br      r12a")
        return out

    # -- statements ---------------------------------------------------------------------------------------

    def note(self, s: Node) -> None:
        text = self.m.texts.get(s.where)
        if text is not None:
            self.code.append("; %d: %s" % (s.where[1], text.strip()))

    def block(self, b: Node, new_scope: bool = True) -> None:
        if new_scope:
            self.m.scopes.append({})
        for s in b.stmts:
            self.statement(s)
        if new_scope:
            self.m.scopes.pop()

    def statement(self, s: Node) -> None:
        assert not self.live, "temps alive between statements"
        if s.kind not in ("block",):
            self.note(s)
        getattr(self, "st_" + s.kind)(s)
        self.spill_all()
        for t in list(self.live):
            self.release(t)

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
        slot = self.new_slot(t.resolved().size)
        loc = FrameLoc(slot)
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
                loc = self.loc(s.target)
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
        if isinstance(loc, PtrLoc):
            self.pin(loc.temp)
        cur = self.load(loc, tt.resolved().size)
        if isinstance(loc, PtrLoc):
            self.unpin(loc.temp)
        res = self.binop(op, cur, s.value, tt, s.where)
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
        self.place(then)
        self.block(s.then)
        self.emit("br      =%s" % end)
        self.place(other)
        if s.els is not None:
            self.block(s.els)
        self.place(end)

    def st_loop(self, s: Node) -> None:
        if s.name is not None and any(n == s.name for n, _, _ in self.loops):
            raise YError("loop '%s' is inside a loop of the same name" % s.name, s.where)
        top, end = self.label(), self.label()
        self.place(top)
        self.loops.append((s.name, top, end))
        self.block(s.body)
        self.loops.pop()
        self.emit("br      =%s" % top)
        self.place(end)

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
        self.emit("br      =%s" % self.find_loop(s)[2])

    def st_continue(self, s: Node) -> None:
        self.emit("br      =%s" % self.find_loop(s)[1])

    def st_return(self, s: Node) -> None:
        ret = self.fnty.ret
        if s.value is None:
            if ret is not None:
                raise YError("this function returns %s; 'return' needs a value" % ret, s.where)
        else:
            if ret is None:
                raise YError("this function returns nothing", s.where)
            self.m.check_value_as(s.value, ret)
            self.put(FrameLoc(self.ret_slot), s.value, ret)
        self.emit("br      =%s" % self.ret_label)

    # -- storing values ----------------------------------------------------------------------------------

    def put(self, loc, e: Node, t: Type) -> None:
        """Store the (checked) value or initialiser e of type t at loc."""
        T = t.resolved()
        if e.kind == "init":
            if isinstance(T, ArrayT):
                esize = T.elem.resolved().size
                for i, el in enumerate(e.elems):
                    self.put(loc.plus(i * esize), el, T.elem)
                rest = T.n - len(e.elems)
                if rest > 0:
                    last = len(e.elems) - 1
                    self.copy(loc.plus(len(e.elems) * esize), loc.plus(last * esize), rest * esize)
            else:
                for name, val, _ in e.fields:
                    off, ft = T.field(name)
                    self.put(loc.plus(off), val, ft)
            return
        if is_aggregate(T):
            src = self.loc(e)
            self.copy(loc, src, T.size)
            self.free_loc(src)
            return
        v = self.val(e)
        self.store(loc, v)
        self.release(v)

    # -- conditions -----------------------------------------------------------------------------------------

    def branch(self, e: Node, yes: str, no: str) -> None:
        """Jump to yes if the condition e holds, else to no.  Nothing stays in registers."""
        self.spill_all()
        if e.const is not None:
            self.emit("br      =%s" % (yes if e.const else no))
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
            self.place(mid)
            self.branch(e.right, yes, no)
            return
        if e.kind == "binary" and e.op in ("eq", "ne", "lt", "le", "gt", "ge"):
            cond = self.compare(e)
            self.emit("br.%-4s =%s" % (cond, yes))
            self.emit("br      =%s" % no)
            return
        v = self.val(e)                       # a bool value
        self.emit("cmp     %s, #1" % v.r(0))
        self.release(v)
        self.emit("br.eq   =%s" % yes)
        self.emit("br      =%s" % no)

    def compare(self, e: Node) -> str:
        """Set the flags for the comparison e; returns the condition suffix."""
        t = e.cmp_ty.resolved()
        n = t.size if not isinstance(t, NullT) else 2
        signed = isinstance(t, IntT) and t.signed
        op = e.op
        if op in ("eq", "ne"):
            a = self.val(e.left)
            b = self.operand(e.right)
            self.ensure(a)
            self.pin(a)
            if n == 1:
                self.emit("cmp     %s, %s" % (a.r(0), self.src(b, 0)))
            else:
                for k in range(n):
                    self.emit("eor     %s, %s, %s" % (a.r(k), a.r(k), self.src(b, k)))
                for k in range(1, n - 1):
                    self.emit("or      %s, %s, %s" % (a.r(0), a.r(0), a.r(k)))
                self.emit("ord     %s, %s" % (a.r(0), a.r(n - 1)))
            self.unpin(a)
            self.release(a)
            if isinstance(b, Temp):
                self.release(b)
            return op
        first, second = (e.left, e.right) if op in ("lt", "ge") else (e.right, e.left)
        a = self.val(first)
        b = self.operand(second)
        self.ensure(a)
        self.pin(a)
        self.emit("cmp     %s, %s" % (a.r(0), self.src(b, 0)))
        for k in range(1, n):
            self.emit("subcd   %s, %s" % (a.r(k), self.src(b, k)))
        self.unpin(a)
        self.release(a)
        if isinstance(b, Temp):
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

    # -- values ---------------------------------------------------------------------------------------------

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
            return self.const(c, size_of(e))
        t = getattr(self, "v_" + e.kind)(e)
        assert t.size == size_of(e) or e.kind in ("as",), (e.kind, t.size, size_of(e))
        return self.ensure(t)

    def v_name(self, e: Node) -> Temp:
        return self.load(e.sym.loc, e.ty.resolved().size)

    def v_index(self, e: Node) -> Temp:
        loc = self.loc(e)
        t = self.load(loc, e.ty.resolved().size)
        self.free_loc(loc)
        return t

    v_field = v_index
    v_deref = v_index

    def v_sstr(self, e: Node) -> Temp:
        label = self.m.string_label(e.data)
        t = self.temp(2)
        self.emit("mova    r10a, =%s" % label)
        self.emit("mov     %s, r10" % t.r(0))
        self.emit("mov     %s, r11" % t.r(1))
        return t

    def v_ptr(self, e: Node) -> Temp:
        x = e.operand
        if x.kind == "name" and x.sym.kind == "func":
            t = self.temp(2)
            self.emit("mova    r10a, =%s" % x.sym.name)
            self.emit("mov     %s, r10" % t.r(0))
            self.emit("mov     %s, r11" % t.r(1))
            return t
        return self.addr_of(self.loc(x))

    def v_call(self, e: Node) -> Temp:
        return self.call(e)

    def v_boolof(self, e: Node) -> Temp:
        self.spill_all()
        t = Temp(1)
        t.slot = self.slot_for(1)
        yes, no, end = self.label(), self.label(), self.label()
        self.branch(e.operand, yes, no)
        for lab, v in ((yes, 1), (no, 0)):
            self.place(lab)
            self.emit("mov     r0, #%d" % v)
            self.frame_addr(t.slot, 0)
            self.emit("str     r0, r10a")
            if v:
                self.emit("br      =%s" % end)
        self.place(end)
        return t

    def v_unary(self, e: Node) -> Temp:
        t = self.val(e.operand)
        n = t.size
        if isinstance(e.ty.resolved(), BoolT):
            self.emit("eor     %s, %s, #1" % (t.r(0), t.r(0)))
            return t
        for k in range(n):
            self.emit("eor     %s, %s, #255" % (t.r(k), t.r(k)))
        if e.op == "-":
            self.add_chain(t, [1] + [0] * (n - 1))
        return t

    def add_chain(self, t: Temp, b, sub: bool = False) -> None:
        n = t.size
        base = "sub" if sub else "add"
        for k in range(n):
            if n == 1:
                ins = base
            elif k == 0:
                ins = base + "s"
            elif k < n - 1:
                ins = base + "cs"
            else:
                ins = base + "c"
            self.emit("%-7s %s, %s, %s" % (ins, t.r(k), t.r(k), self.src(b, k)))

    def v_binary(self, e: Node) -> Temp:
        if e.op in ("shl", "shr", "sar", "rol", "ror"):
            return self.shift(e)
        left = self.val(e.left)
        return self.binop(e.op, left, e.right, e.ty, e.where)

    def binop(self, op: str, left: Temp, right: Node, ty: Type, where: tuple[str, int]) -> Temp:
        """left op right, in place in left's registers (consumes left)."""
        T = ty.resolved()
        if op in ("*", "/", "%"):
            fn = self.m.helper(op, T)
            r = self.val(right)
            return self.call_helper(fn.name, [left, r], T.size)
        b = self.operand(right)
        self.ensure(left)
        self.pin(left)
        if op in ("+", "-"):
            self.add_chain(left, b, sub=(op == "-"))
        else:
            ins = {"&": "and", "|": "or", "^": "eor"}[op]
            for k in range(left.size):
                self.emit("%-7s %s, %s, %s" % (ins, left.r(k), left.r(k), self.src(b, k)))
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
        if c is not None:
            if e.op in ("rol", "ror"):
                c %= w
            else:
                c = min(c, w)
            if c == 0:
                return v
            if c * n <= 24:
                for _ in range(c):
                    self.shift1(e.op, v)
                return v
            self.pin(v)
            cnt = self.const(c, 1)
            self.unpin(v)
        else:
            cnt = self.val(e.right)                 # v may be spilled meanwhile
            c0 = cnt.r(0)
            if e.op in ("rol", "ror"):
                self.emit("and     %s, %s, #%d" % (c0, c0, w - 1))
            else:
                for k in range(1, cnt.size):
                    self.emit("cmp     %s, #0" % cnt.r(k))
                    self.emit("mov.ne  %s, #%d" % (c0, w))
                self.emit("cmp     %s, #%d" % (c0, w))
                self.emit("mov.gu  %s, #%d" % (c0, w))
        self.pin(cnt)
        self.ensure(v)
        self.pin(v)
        top, done = self.label(), self.label()
        self.place(top)
        self.emit("cmp     %s, #0" % cnt.r(0))
        self.emit("br.eq   =%s" % done)
        self.shift1(e.op, v)
        self.emit("sub     %s, %s, #1" % (cnt.r(0), cnt.r(0)))
        self.emit("br      =%s" % top)
        self.place(done)
        self.unpin(v, cnt)
        self.release(cnt)
        return v

    def shift1(self, op: str, v: Temp) -> None:
        n = v.size
        r = [v.r(k) for k in range(n)]
        if op == "shl":
            for k in range(n):
                ins = "lsl" if k == 0 and n == 1 else ("lsls" if k == 0 else ("csls" if k < n - 1 else "csl"))
                self.emit("%-7s %s, %s" % (ins, r[k], r[k]))
        elif op in ("shr", "sar"):
            first = "lsr" if op == "shr" else "asr"
            for i, k in enumerate(range(n - 1, -1, -1)):
                if i == 0:
                    ins = first if n == 1 else first + "s"
                else:
                    ins = "csrs" if k > 0 else "csr"
                self.emit("%-7s %s, %s" % (ins, r[k], r[k]))
        elif op == "rol":
            self.emit("lsld    %s" % r[n - 1])
            for k in range(n):
                self.emit("%-7s %s, %s" % ("csls" if k < n - 1 else "csl", r[k], r[k]))
        else:
            self.emit("lsrd    %s" % r[0])
            for k in range(n - 1, -1, -1):
                self.emit("%-7s %s, %s" % ("csrs" if k > 0 else "csr", r[k], r[k]))

    def v_cast(self, e: Node) -> Temp:
        S = e.operand.ty.resolved()
        D = e.ty.resolved()
        t = self.val(e.operand)
        if isinstance(D, BoolT):
            if isinstance(S, BoolT):
                return t
            n = t.size
            for k in range(1, n - 1):
                self.emit("or      %s, %s, %s" % (t.r(0), t.r(0), t.r(k)))
            self.emit("ord     %s, %s" % (t.r(0), t.r(n - 1) if n > 1 else "#0"))
            self.emit("mov.ne  %s, #1" % t.r(0))
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
        xs = size_of(x)
        if xs != D.size and (self.m.is_lvalue(x) or is_aggregate(x.ty)):
            loc = self.loc(x)
            t = self.load(loc, D.size)
            self.free_loc(loc)
            return t
        if is_aggregate(x.ty):
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

    # -- locations ------------------------------------------------------------------------------------------

    def loc(self, e: Node):
        """The memory of an lvalue or an aggregate value."""
        k = e.kind
        if k == "name":
            if e.sym.kind != "var":
                raise YError("'%s' is not a variable" % e.name, e.where)
            return e.sym.loc
        if k == "deref":
            return PtrLoc(self.val(e.ptr))
        if k == "field":
            return self.loc(e.obj).plus(e.offset)
        if k == "index":
            ot = e.obj.ty.resolved()
            esize = e.ty.resolved().size
            base = self.loc(e.obj) if isinstance(ot, ArrayT) else PtrLoc(self.val(e.obj))
            c = self.cval(e.index)
            if c is not None:
                return base.plus(c * esize)
            a = self.addr_of(base)
            i = self.val(e.index)
            self.extend(i, 2, e.index.ty.resolved().signed)
            self.scale(i, esize)
            self.pin(i)
            self.ensure(a)
            self.unpin(i)
            self.emit("adds    %s, %s, %s" % (a.r(0), a.r(0), i.r(0)))
            self.emit("addc    %s, %s, %s" % (a.r(1), a.r(1), i.r(1)))
            self.release(i)
            return PtrLoc(a)
        if k == "str":
            return GlobalLoc(self.m.string_label(e.data))
        if k == "call":
            return self.call(e)
        if k == "as":
            x = e.operand
            if self.m.is_lvalue(x) or is_aggregate(x.ty):
                return self.loc(x)
            v = self.val(x)
            slot = self.new_slot(max(v.size, e.ty.resolved().size))
            loc = FrameLoc(slot)
            self.store(loc, v)
            self.release(v)
            return loc
        if k == "init":
            slot = self.new_slot(e.ty.resolved().size)
            loc = FrameLoc(slot)
            self.put(loc, e, e.ty)
            return loc
        raise YError("this expression has no memory location", e.where)

    def scale(self, i: Temp, size: int) -> None:
        """i (2 bytes, in registers) *= size, by shifts and adds."""
        if size == 1:
            return
        if size & (size - 1) == 0:
            for _ in range(size.bit_length() - 1):
                self.emit("lsls    %s, %s" % (i.r(0), i.r(0)))
                self.emit("csl     %s, %s" % (i.r(1), i.r(1)))
            return
        self.pin(i)
        acc = self.const(0, 2)
        self.unpin(i)
        bit = 1
        while bit <= size:
            if size & bit:
                self.emit("adds    %s, %s, %s" % (acc.r(0), acc.r(0), i.r(0)))
                self.emit("addc    %s, %s, %s" % (acc.r(1), acc.r(1), i.r(1)))
            bit <<= 1
            if bit <= size:
                self.emit("lsls    %s, %s" % (i.r(0), i.r(0)))
                self.emit("csl     %s, %s" % (i.r(1), i.r(1)))
        for k in range(2):
            self.emit("mov     %s, %s" % (i.r(k), acc.r(k)))
        self.release(acc)

    # -- calls ------------------------------------------------------------------------------------------------

    def call(self, e: Node):
        fnty = e.fnty
        fp = None
        if e.direct is None:
            fp = self.val(e.func)
        writers = []
        for a, p in zip(e.args, fnty.params):
            writers.append((p.resolved().size, lambda loc, a=a, p=p: self.put(loc, a, p)))
        ret = fnty.ret
        R = ret.resolved().size if ret else 0
        target = e.direct.name if e.direct is not None else fp
        return self.emit_call(target, writers, R, ret is not None and is_aggregate(ret))

    def call_helper(self, name: str, args: list[Temp], R: int) -> Temp:
        writers = [(t.size, lambda loc, t=t: (self.store(loc, t), self.release(t))) for t in args]
        return self.emit_call(name, writers, R, False)

    def emit_call(self, target, writers, R: int, aggregate: bool):
        if isinstance(target, Temp):
            self.spill(target)
        self.spill_all()
        A = R + sum(size for size, _ in writers)
        if A:
            self.sp_sub(A)
            self.sp_delta += A
        delta = self.sp_delta
        off = R
        for size, write in writers:
            write(SpLoc(off, delta))
            self.spill_all()
            off += size
        if isinstance(target, Temp):
            self.ensure(target)
            self.emit("mov     r10, %s" % target.r(0))
            self.emit("mov     r11, %s" % target.r(1))
            self.release(target)
            self.spill_all()
            self.emit("brl     r12a, r10a")
        else:
            self.spill_all()
            self.emit("brl     r12a, =%s" % target)
        result = None
        if R and not aggregate:
            result = self.temp(R)
            for k in range(R):
                self.sp_addr(1 + k)
                self.emit("ldr     %s, r10a" % result.r(k))
        elif R:
            slot = self.new_slot(R)
            result = FrameLoc(slot)
            self.copy(result, SpLoc(0, delta), R)
        if A:
            self.sp_add(A)
            self.sp_delta -= A
        return result


def size_of(e: Node) -> int:
    t = getattr(e, "conv", None) or e.ty
    t = t.resolved()
    if isinstance(t, NullT):
        return 2
    return t.size
