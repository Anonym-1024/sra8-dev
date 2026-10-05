"""Recursive-descent parser of Y (docs/y.md 14), producing ast.Node trees.

Node kinds and their attributes:

top level   decl(name, type | is_type, recursive)  typedef(name, type)
            impl(name, params, ret, body, internal, recursive, main, section)
            var(name, type, value, internal)        value: expression, init or None for `undefined`
types       tname(name)  tptr(target)  tmany(target)  tarray(length | None for _, elem)
            tstruct(fields, union)  tfn(params, ret)
statements  block(stmts)  var  assign(target, op, value)  callstmt(call)  discard(value)
            if(cond, then, els)  loop(name, body)  break(name)  continue(name)  return(value)
expressions int(value)  str(data)  sstr(data)  true  false  nullptr  name(name)
            unary(op, operand)  binary(op, left, right)  call(func, args)  index(obj, index)
            field(obj, name)  deref(ptr)  ptr(operand)  sizeof(type)  boolof(operand)
            as(type, operand)  cast(type, operand)
            init(elems, fields, fill)               elems: list, or fields: [(name, value, where)]
"""

from __future__ import annotations

from .ast import Node
from .errors import YError
from .lexer import Token

ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^="}
CMP_OPS = {"eq", "ne", "lt", "le", "gt", "ge"}
BIT_OPS = {"&", "|", "^", "shl", "shr", "sar", "rol", "ror"}
BUILTIN_TYPE_NAMES = {"int8", "int16", "int32", "uint8", "uint16", "uint32", "byte", "char", "addr",
                      "bool", "opaque"}


class Parser:
    def __init__(self, toks: list[Token]) -> None:
        self.toks = toks
        self.i = 0

    # -- token helpers ------------------------------------------------------------

    @property
    def tok(self) -> Token:
        return self.toks[self.i]

    def peek(self, k: int = 1) -> Token:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def at(self, text: str) -> bool:
        t = self.tok
        return t.kind in ("p", "kw", "builtin") and t.text == text

    def take(self) -> Token:
        t = self.tok
        if t.kind != "eof":
            self.i += 1
        return t

    def accept(self, text: str) -> bool:
        if self.at(text):
            self.i += 1
            return True
        return False

    def expect(self, text: str) -> Token:
        if not self.at(text):
            raise YError("expected '%s', found '%s'" % (text, self.tok.text), self.tok.where)
        return self.take()

    def ident(self) -> str:
        if self.tok.kind != "name":
            raise YError("expected a name, found '%s'" % self.tok.text, self.tok.where)
        return self.take().text

    # -- top level ----------------------------------------------------------------

    def file(self) -> list[Node]:
        items = []
        while self.tok.kind != "eof":
            items.append(self.top_item())
        return items

    def top_item(self) -> Node:
        where = self.tok.where
        main, section, internal, recursive = False, None, False, False
        while self.tok.kind == "builtin":
            b = self.take().text
            if b == "@main":
                main = True
            elif b == "@section":
                self.expect("(")
                section = self.ident()
                self.expect(")")
            elif b == "@internal":
                internal = True
            elif b == "@recursive":
                recursive = True
            elif b == "@reg":
                raise YError("@reg is not supported by ylangc", where)
            else:
                raise YError("'%s' is not an attribute" % b, where)
        if self.at("impl"):
            node = self.impl(internal)
            node.main, node.section, node.recursive = main, section, recursive
            return node
        if main or section:
            raise YError("@main and @section apply to 'impl' only", where)
        if self.at("var"):
            if recursive:
                raise YError("@recursive applies to functions only", where)
            return self.var(internal)
        if internal:
            raise YError("@internal applies to 'impl' and 'var' only", where)
        if self.accept("decl"):
            name = self.ident()
            self.expect(":")
            if self.accept("type"):
                if recursive:
                    raise YError("@recursive applies to functions only", where)
                self.expect(";")
                return Node("decl", where, name=name, type=None, is_type=True, recursive=False)
            t = self.type_()
            self.expect(";")
            return Node("decl", where, name=name, type=t, is_type=False, recursive=recursive)
        if recursive:
            raise YError("@recursive applies to 'impl' and 'decl' of a function", where)
        if self.accept("type"):
            name = self.ident()
            self.expect("=")
            t = self.type_()
            self.expect(";")
            return Node("typedef", where, name=name, type=t)
        raise YError("expected a declaration, found '%s'" % self.tok.text, where)

    def impl(self, internal: bool) -> Node:
        where = self.expect("impl").where
        name = self.ident()
        self.expect(":")
        self.expect("fn")
        self.expect("(")
        params = []
        while not self.at(")"):
            pw = self.tok.where
            pname = self.ident()
            self.expect(":")
            params.append((pname, self.type_(), pw))
            if not self.accept(","):
                break
        self.expect(")")
        ret = self.type_() if self.accept("returns") else None
        body = self.block()
        return Node("impl", where, name=name, params=params, ret=ret, body=body, internal=internal,
                    recursive=False, main=False, section=None)

    def var(self, internal: bool) -> Node:
        where = self.expect("var").where
        name = self.ident()
        self.expect(":")
        t = self.type_()
        self.expect("=")
        if self.accept("undefined"):
            value = None
        else:
            value = self.value()
        self.expect(";")
        return Node("var", where, name=name, type=t, value=value, internal=internal)

    # -- types ------------------------------------------------------------------------

    def type_(self) -> Node:
        where = self.tok.where
        if self.accept("*"):
            return Node("tptr", where, target=self.type_())
        if self.accept("["):
            if self.accept("*"):
                self.expect("]")
                return Node("tmany", where, target=self.type_())
            if self.accept("_"):
                length = None
            else:
                length = self.expr()
            self.expect("]")
            return Node("tarray", where, length=length, elem=self.type_())
        t = self.tok
        if t.kind == "kw" and t.text in BUILTIN_TYPE_NAMES:
            self.take()
            return Node("tname", where, name=t.text)
        if t.kind == "name":
            self.take()
            return Node("tname", where, name=t.text)
        if t.text in ("struct", "union") and t.kind == "kw":
            self.take()
            self.expect("{")
            fields = []
            while not self.at("}"):
                fw = self.tok.where
                fname = self.ident()
                self.expect(":")
                fields.append((fname, self.type_(), fw))
                if not self.accept(","):
                    break
            self.expect("}")
            if not fields:
                raise YError("a %s needs at least one field" % t.text, where)
            return Node("tstruct", where, fields=fields, union=t.text == "union")
        if self.accept("fn"):
            self.expect("(")
            params = []
            while not self.at(")"):
                pname = None
                if self.tok.kind == "name" and self.peek().text == ":" and self.peek().kind == "p":
                    pname = self.take().text
                    self.take()
                params.append((pname, self.type_()))
                if not self.accept(","):
                    break
            self.expect(")")
            ret = self.type_() if self.accept("returns") else None
            return Node("tfn", where, params=params, ret=ret)
        raise YError("expected a type, found '%s'" % t.text, where)

    # -- statements ---------------------------------------------------------------------

    def block(self) -> Node:
        where = self.expect("{").where
        stmts = []
        while not self.at("}"):
            if self.tok.kind == "eof":
                raise YError("missing '}'", self.tok.where)
            stmts.append(self.statement())
        self.expect("}")
        return Node("block", where, stmts=stmts)

    def statement(self) -> Node:
        t = self.tok
        where = t.where
        if t.kind == "builtin":
            if t.text == "@reg":
                raise YError("@reg is not supported by ylangc", where)
            if t.text in ("@main", "@section", "@internal", "@recursive"):
                raise YError("%s applies to a top-level 'impl'" % t.text, where)
        if self.at("var"):
            return self.var(False)
        if self.at("{"):
            return self.block()
        if self.accept("if"):
            return self.if_rest(where)
        if self.accept("loop"):
            name = self.ident() if self.tok.kind == "name" else None
            return Node("loop", where, name=name, body=self.block())
        if self.accept("break") or self.accept("continue"):
            kind = t.text
            name = self.ident() if self.tok.kind == "name" else None
            self.expect(";")
            return Node(kind, where, name=name)
        if self.accept("return"):
            value = None if self.at(";") else self.value()
            self.expect(";")
            return Node("return", where, value=value)
        if self.at("_") and self.peek().text == "=":
            self.take()
            self.take()
            value = self.expr()
            self.expect(";")
            return Node("discard", where, value=value)
        target = self.expr()
        if self.tok.kind == "p" and self.tok.text in ASSIGN_OPS:
            op = self.take().text
            value = self.value()
            self.expect(";")
            return Node("assign", where, target=target, op=op, value=value)
        self.expect(";")
        if target.kind != "call":
            raise YError("only a call, an assignment or '_ = …' can be a statement", where)
        return Node("callstmt", where, call=target)

    def if_rest(self, where: tuple[str, int]) -> Node:
        self.expect("(")
        cond = self.expr()
        self.expect(")")
        then = self.block()
        els = None
        if self.accept("else"):
            if self.at("if"):
                w = self.take().where
                els = Node("block", w, stmts=[self.if_rest(w)])
            else:
                els = self.block()
        return Node("if", where, cond=cond, then=then, els=els)

    # -- values and initialisers ------------------------------------------------------------

    def value(self) -> Node:
        return self.init() if self.at("{") else self.expr()

    def init(self) -> Node:
        where = self.expect("{").where
        if self.tok.kind == "name" and self.peek().text == "=" and self.peek().kind == "p":
            fields = []
            while not self.at("}"):
                fw = self.tok.where
                fname = self.ident()
                self.expect("=")
                fields.append((fname, self.value(), fw))
                if not self.accept(","):
                    break
            self.expect("}")
            return Node("init", where, elems=None, fields=fields, fill=False)
        elems = []
        fill = False
        while not self.at("}"):
            if self.at("_"):
                fw = self.take().where
                if not elems:
                    raise YError("'_' repeats the value before it, so it cannot come first", fw)
                fill = True
                self.accept(",")
                break
            elems.append(self.value())
            if not self.accept(","):
                break
        self.expect("}")
        if not elems:
            raise YError("an initialiser needs at least one value", where)
        return Node("init", where, elems=elems, fields=None, fill=fill)

    # -- expressions (docs/y.md 11.2, lowest level first) -------------------------------------

    def expr(self) -> Node:
        left = self.not_()
        while self.tok.kind == "kw" and self.tok.text in ("and", "or"):
            t = self.take()
            left = Node("binary", t.where, op=t.text, left=left, right=self.not_())
        return left

    def not_(self) -> Node:
        if self.at("not"):
            w = self.take().where
            return Node("unary", w, op="not", operand=self.not_())
        return self.compare()

    def compare(self) -> Node:
        left = self.additive()
        if self.tok.kind == "kw" and self.tok.text in CMP_OPS:
            t = self.take()
            left = Node("binary", t.where, op=t.text, left=left, right=self.additive())
            if self.tok.kind == "kw" and self.tok.text in CMP_OPS:
                raise YError("a comparison cannot be compared again; a condition is not a value", self.tok.where)
        return left

    def additive(self) -> Node:
        left = self.multiplicative()
        while self.tok.kind == "p" and self.tok.text in ("+", "-"):
            t = self.take()
            left = Node("binary", t.where, op=t.text, left=left, right=self.multiplicative())
        return left

    def multiplicative(self) -> Node:
        left = self.bitwise()
        while self.tok.kind == "p" and self.tok.text in ("*", "/", "%"):
            t = self.take()
            left = Node("binary", t.where, op=t.text, left=left, right=self.bitwise())
        return left

    def bitwise(self) -> Node:
        left = self.prefix()
        while self.tok.kind in ("p", "kw") and self.tok.text in BIT_OPS:
            t = self.take()
            left = Node("binary", t.where, op=t.text, left=left, right=self.prefix())
        return left

    def prefix(self) -> Node:
        t = self.tok
        if t.kind == "p" and t.text in ("-", "~"):
            self.take()
            return Node("unary", t.where, op=t.text, operand=self.prefix())
        return self.postfix()

    def postfix(self) -> Node:
        e = self.primary()
        while True:
            t = self.tok
            if self.accept("("):
                args = []
                while not self.at(")"):
                    args.append(self.value())
                    if not self.accept(","):
                        break
                self.expect(")")
                e = Node("call", t.where, func=e, args=args)
            elif self.accept("["):
                idx = self.expr()
                self.expect("]")
                e = Node("index", t.where, obj=e, index=idx)
            elif self.accept("."):
                e = Node("field", t.where, obj=e, name=self.ident())
            else:
                return e

    def primary(self) -> Node:
        t = self.tok
        w = t.where
        if t.kind in ("num", "char"):
            self.take()
            return Node("int", w, value=t.value)
        if t.kind == "str":
            self.take()
            return Node("str", w, data=t.value)
        if t.kind == "sstr":
            self.take()
            return Node("sstr", w, data=t.value)
        if t.kind == "name":
            self.take()
            return Node("name", w, name=t.text)
        if t.kind == "kw" and t.text in ("true", "false", "nullptr"):
            self.take()
            return Node(t.text, w)
        if self.accept("("):
            e = self.expr()
            self.expect(")")
            return e
        if self.accept("["):
            e = self.expr()
            self.expect("]")
            return Node("deref", w, ptr=e)
        if t.kind == "builtin":
            self.take()
            if t.text in ("@ptr", "@bool"):
                self.expect("(")
                e = self.expr()
                self.expect(")")
                return Node("ptr" if t.text == "@ptr" else "boolof", w, operand=e)
            if t.text == "@sizeof":
                self.expect("(")
                ty = self.type_()
                self.expect(")")
                return Node("sizeof", w, type=ty)
            if t.text in ("@as", "@cast"):              # @as(T, x)  @cast(T, x)
                self.expect("(")
                ty = self.type_()
                if not self.accept(","):
                    raise YError("%s takes a type and a value: %s(T, x)" % (t.text, t.text), self.tok.where)
                e = self.expr()
                self.expect(")")
                return Node(t.text[1:], w, type=ty, operand=e)
            raise YError("'%s' cannot be used in an expression" % t.text, w)
        if t.kind == "p" and t.text == "{":
            raise YError("an initialiser '{…}' is only allowed where its type is known", w)
        raise YError("expected an expression, found '%s'" % t.text, w)


def parse(toks: list[Token]) -> list[Node]:
    return Parser(toks).file()
