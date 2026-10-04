"""Syntax tree nodes.  One generic class: `kind` says what it is, the other
attributes depend on the kind (see parser.py).  The checker adds `ty`
(the type) and `const` (the value of a constant expression)."""

from __future__ import annotations


class Node:
    def __init__(self, kind: str, where: tuple[str, int], **attrs: object) -> None:
        self.kind = kind
        self.where = where
        self.ty = None
        self.const: int | None = None
        self.__dict__.update(attrs)

    def __repr__(self) -> str:
        keys = [k for k in self.__dict__ if k not in ("kind", "where", "ty", "const")]
        return "%s(%s)" % (self.kind, ", ".join("%s=%r" % (k, self.__dict__[k]) for k in keys))
