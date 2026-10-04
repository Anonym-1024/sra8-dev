"""The types of Y (docs/y.md 5)."""

from __future__ import annotations

import itertools


class Type:
    def resolved(self) -> "Type":
        return self

    @property
    def complete(self) -> bool:
        return True

    @property
    def size(self) -> int:
        raise NotImplementedError


class IntT(Type):
    def __init__(self, name: str, size: int, signed: bool) -> None:
        self.name, self._size, self.signed = name, size, signed

    @property
    def size(self) -> int:
        return self._size

    @property
    def bits(self) -> int:
        return self._size * 8

    def range(self) -> tuple[int, int]:
        if self.signed:
            return -(1 << (self.bits - 1)), (1 << (self.bits - 1)) - 1
        return 0, (1 << self.bits) - 1

    def __str__(self) -> str:
        return self.name


class BoolT(Type):
    size = 1

    def __str__(self) -> str:
        return "bool"


class OpaqueT(Type):
    complete = False

    def __str__(self) -> str:
        return "opaque"


class NullT(Type):
    """The type of nullptr: converts to every pointer."""
    size = 2

    def __str__(self) -> str:
        return "nullptr"


class CondT(Type):
    """The 'type' of a condition (docs/y.md 11.1): not a value."""
    complete = False

    def __str__(self) -> str:
        return "condition"


class PtrT(Type):
    size = 2

    def __init__(self, target: Type) -> None:
        self.target = target

    def __str__(self) -> str:
        return "*" + str(self.target)


class ManyT(Type):
    size = 2

    def __init__(self, target: Type) -> None:
        self.target = target

    def __str__(self) -> str:
        return "[*]" + str(self.target)


class ArrayT(Type):
    def __init__(self, n: int, elem: Type) -> None:
        self.n, self.elem = n, elem

    @property
    def complete(self) -> bool:
        return self.elem.resolved().complete

    @property
    def size(self) -> int:
        return self.n * self.elem.resolved().size

    def __str__(self) -> str:
        return "[%d]%s" % (self.n, self.elem)


_uids = itertools.count(1)


class StructT(Type):
    """A struct or a union.  Each one written in the source is distinct."""

    def __init__(self, fields: list[tuple[str, Type]], union: bool) -> None:
        self.fields = fields
        self.union = union
        self.uid = next(_uids)
        self.name: str | None = None        # the first type name given to it, for messages

    def field(self, name: str) -> tuple[int, Type] | None:
        off = 0
        for n, t in self.fields:
            if n == name:
                return (0 if self.union else off), t
            off += t.resolved().size
        return None

    @property
    def size(self) -> int:
        sizes = [t.resolved().size for _, t in self.fields]
        return max(sizes) if self.union else sum(sizes)

    def __str__(self) -> str:
        if self.name:
            return self.name
        return "%s{%s}" % ("union" if self.union else "struct",
                           ", ".join("%s: %s" % (n, t) for n, t in self.fields))


class FnT(Type):
    complete = False

    def __init__(self, params: list[Type], ret: Type | None, names: list[str | None] | None = None) -> None:
        self.params = params
        self.ret = ret
        self.names = names or [None] * len(params)

    def __str__(self) -> str:
        s = "fn(%s)" % ", ".join(str(p) for p in self.params)
        return s + (" returns %s" % self.ret if self.ret else "")


class NamedT(Type):
    """A type name from `decl name: type;`, incomplete until `type name = T;`."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.target: Type | None = None

    def resolved(self) -> Type:
        t: Type = self
        seen = 0
        while isinstance(t, NamedT) and t.target is not None and seen < 100:
            t = t.target
            seen += 1
        return t

    @property
    def complete(self) -> bool:
        r = self.resolved()
        return not isinstance(r, NamedT) and r.complete

    @property
    def size(self) -> int:
        return self.resolved().size

    def __str__(self) -> str:
        return self.name


INT8 = IntT("int8", 1, True)
INT16 = IntT("int16", 2, True)
INT32 = IntT("int32", 4, True)
UINT8 = IntT("uint8", 1, False)
UINT16 = IntT("uint16", 2, False)
UINT32 = IntT("uint32", 4, False)
BOOL = BoolT()
OPAQUE = OpaqueT()
NULL = NullT()
COND = CondT()

BUILTIN_TYPES: dict[str, Type] = {
    "int8": INT8, "int16": INT16, "int32": INT32,
    "uint8": UINT8, "uint16": UINT16, "uint32": UINT32,
    "byte": UINT8, "char": UINT8, "addr": UINT16,
    "bool": BOOL, "opaque": OPAQUE,
}


def same(a: Type | None, b: Type | None) -> bool:
    if a is None or b is None:
        return a is b
    a, b = a.resolved(), b.resolved()
    if a is b:
        return True
    if type(a) is not type(b):
        return False
    if isinstance(a, (PtrT, ManyT)):
        return same(a.target, b.target)            # type: ignore[attr-defined]
    if isinstance(a, ArrayT):
        return a.n == b.n and same(a.elem, b.elem)  # type: ignore[attr-defined]
    if isinstance(a, FnT):
        return (len(a.params) == len(b.params) and all(same(x, y) for x, y in zip(a.params, b.params))  # type: ignore[attr-defined]
                and same(a.ret, b.ret))            # type: ignore[attr-defined]
    return False


def is_int(t: Type | None) -> bool:
    return t is not None and isinstance(t.resolved(), IntT)


def is_ptr(t: Type | None) -> bool:
    return t is not None and isinstance(t.resolved(), (PtrT, ManyT, NullT))


def is_scalar(t: Type) -> bool:
    return isinstance(t.resolved(), (IntT, BoolT, PtrT, ManyT, NullT))


def is_aggregate(t: Type) -> bool:
    return isinstance(t.resolved(), (ArrayT, StructT))


def implicit(src: Type, dst: Type) -> bool:
    """May a value of type src be used where dst is required (docs/y.md 8.2)?"""
    s, d = src.resolved(), dst.resolved()
    if same(s, d):
        return True
    if isinstance(s, NullT):
        return isinstance(d, (PtrT, ManyT))
    if isinstance(s, (PtrT, ManyT)):
        if isinstance(d, PtrT) and isinstance(d.target.resolved(), OpaqueT):
            return True
        if isinstance(d, IntT) and d is UINT16:
            return True
        st = s.target.resolved()
        if isinstance(s, PtrT) and isinstance(st, ArrayT):
            if isinstance(d, ManyT) and same(st.elem, d.target):          # *[n]T -> [*]T
                return True
            if isinstance(d, PtrT) and same(st.elem, d.target):           # *[n]T -> *T
                return True
        if isinstance(s, ManyT) and isinstance(d, PtrT) and same(s.target, d.target):   # [*]T -> *T
            return True
    return False
