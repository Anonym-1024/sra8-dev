# The Y language

Y is the small systems language of the SRA-8 development kit. This document
defines its syntax and meaning. It was formalised from the draft
`examples/asm/echo.y` and the answers in `examples/asm/y_clarifications.txt`
and `y_clarifications2.txt`.

**Status.** There is no compiler yet. The calling convention, the code
generation and access to the hardware are **not specified** (Section 13).
Everything else here is binding for the future compiler `ylangc`, which
translates one `.y` file into one assembly file (`.s`) for `sra8-as` and
does nothing else.

---

## 1. Overview

```
!INCLUDE uart.yh                        // declarations of another file

type point = struct{x: int16, y: int16};

var origin: point = {x = 0, y = 0};     // exported global
@internal var count: uint8 = 0;         // visible in this file only

impl manhattan: fn(a: *point, b: *point) returns int16 {
    var dx: int16 = [a].x - [b].x;
    var dy: int16 = [a].y - [b].y;
    if (dx lt 0) { dx = -dx; }
    if (dy lt 0) { dy = -dy; }
    return dx + dy;
}
```

In short:

- **Declarations** name first, type second: `var x: T = value;`,
  `impl f: fn(a: T) returns R { … }`, `decl g: fn(T) returns R;`,
  `type name = T;`.
- **Types are written as prefixes**, read left to right: `*T` pointer,
  `[*]T` pointer to many, `[n]T` array, so `*[4]int8` is a pointer to an
  array of four `int8`.
- **Brackets dereference:** `[p]` is the value `p` points to.
- **Logic is words:** `eq ne lt le gt ge`, `not and or`. Conditions are
  not numbers; `@bool(…)` turns one into a `bool`.
- **Arrays and structs are values:** assigning one copies it.
- **Builtins start with `@`:** `@ptr`, `@sizeof`, `@as`, `@cast`, `@bool`,
  and the attributes `@main`, `@section`, `@reg`.
- **The preprocessor** is a line-based text layer (`!INCLUDE`, `!DEFINE`,
  `!IFDEF` …) shared in style with the assembler.

---

## 2. Source files

| Extension | Content |
|---|---|
| `.y` | A translation unit: one input of the compiler. |
| `.yh` | A header: declarations and types, included with `!INCLUDE`. |

Source text is bytes (ASCII; other bytes only inside comments, character
and string literals, where they stand for themselves). Lines end with
`\n` or `\r\n`.

---

## 3. Preprocessor

The preprocessor works on lines before anything else. A **directive** is a
line that starts (after blanks) with one of the directive names below. Comments are removed before directives are read, so a
directive may end with a `//` comment.

| Directive | Meaning |
|---|---|
| `!INCLUDE path` | Replace the line with the contents of the file. The path is the rest of the line, without quotes. It is looked up relative to the directory of the file that contains the directive, then in each `-I dir` in command-line order. Nesting depth is limited to 32. |
| `!DEFINE NAME text` | Define the alias `NAME` as the rest of the line (blanks around it removed; may be empty). Defining a name twice is an error. |
| `!IFDEF NAME` | Keep the following lines only if `NAME` is defined. |
| `!IFNDEF NAME` | Keep the following lines only if `NAME` is not defined. |
| `!ELSE` | Keep the following lines only if no earlier branch of this conditional was kept. |
| `!ELSE IFDEF NAME`, `!ELSE IFNDEF NAME` | Like `!ELSE`, combined with the test of `!IFDEF` / `!IFNDEF`. |
| `!ENDIF` | End the conditional. |

Conditionals nest. Every `!IFDEF` / `!IFNDEF` needs its `!ENDIF` in the
same file.

**Alias use.** Anywhere outside comments and literals, `!NAME` is replaced
by the text of the alias; this includes the path of `!INCLUDE`, but not the
name that `!DEFINE`, `!IFDEF` or `!IFNDEF` acts on. The replacement is scanned again for
further `!NAME` uses (a cycle is an error). Using an undefined alias is an
error. Names given with `-D NAME=text` on the command line are defined
before the first line (`-D NAME` defines it as empty).

Include guard:

```
!IFNDEF UART_YH
!DEFINE UART_YH
decl uart_putc: fn(c: char);
!ENDIF
```

---

## 4. Lexical structure

### 4.1 Comments and blanks

- `// …` to the end of the line.
- `/* … */`, possibly over several lines. Block comments **do not nest**:
  the first `*/` ends the comment.
- Blanks (space, tab, newline) separate tokens and are otherwise ignored.

### 4.2 Identifiers

`[A-Za-z_][A-Za-z0-9_]*`, case-sensitive. A name may not be a keyword.
`_` alone is a keyword (`[_]T` in 5.4, the fill of 9.1, the discard of 10.3). Names starting with
`__` are reserved for the toolchain.

### 4.3 Keywords

*Provisional; the final list will be fixed later.*

```
decl  impl  var  type  fn  returns  struct  union  opaque
if  else  loop  break  continue  return
eq  ne  lt  le  gt  ge  not  and  or
shl  shr  sar  rol  ror
true  false  nullptr  undefined  _
int8  int16  int32  uint8  uint16  uint32  byte  char  bool  addr
```

Builtins are written with a leading `@` and are not keywords:
`@bool @sizeof @as @cast @ptr @main @section @reg @internal @recursive`. Any other `@name` is an
error.

### 4.4 Integer literals

| Form | Example | Base |
|---|---|---|
| digits | `123` | 10 |
| `0d` digits | `0d123` | 10 |
| `0x` hex digits | `0x7B` | 16 |
| `0o` octal digits | `0o173` | 8 |
| `0b` binary digits | `0b1111011` | 2 |

The prefix letter may be upper or lower case, hex digits too. A literal has
no sign (`-5` is the operator `-` applied to `5`) and no suffix. Its value
must fit in 32 bits. Its type comes from the context (Section 8.1).

### 4.5 Character literals

`'a'`, or an escape: `'\n'` (10), `'\t'` (9), `'\r'` (13), `'\0'` (0),
`'\\'`, `'\''`, `'\"'`. A character literal is an integer constant with the
value of the byte; like any integer literal it takes its type from the
context (usually `char`).

### 4.6 String literals

| Form | Type | Meaning |
|---|---|---|
| `"Hello."` | `[7]char` | An array value: the characters followed by a zero byte. |
| `s"Hello."` | `*[7]char` | A pointer to a static array holding the same bytes. |

The escapes of 4.5 are allowed. A string may not span lines. Each `s"…"`
occurrence has its own storage, which may be written (Y has no read-only
data).

### 4.7 Other literals

`true`, `false` (type `bool`), `nullptr` (converts to every pointer type),
`undefined` (only as the initial value of a global variable, 7.3).

### 4.8 Punctuation and operators

```
{ } ( ) [ ] , ; : . =
+ - * / % & | ^ ~
+= -= *= /= %= &= |= ^=
```

---

## 5. Types

### 5.1 Integers

| Type | Size | Range |
|---|---|---|
| `int8` | 1 | −128 … 127 |
| `int16` | 2 | −32 768 … 32 767 |
| `int32` | 4 | −2³¹ … 2³¹−1 |
| `uint8` | 1 | 0 … 255 |
| `uint16` | 2 | 0 … 65 535 |
| `uint32` | 4 | 0 … 2³²−1 |

Signed integers are two's complement. Multi-byte values are stored
**little-endian** (lowest byte at the lowest address).

**Aliases.** `byte` and `char` are the same type as `uint8`; `addr` is the
same type as `uint16`. They are names, not new types: no conversion is
involved.

### 5.2 `bool`

One byte. `true` is stored as 1, `false` as 0. `bool` is a separate type:
it is not an integer, and integers do not become `bool` implicitly
(Section 8).

### 5.3 Pointers

Every pointer is an address: 2 bytes, little-endian.

| Type | Name | Points to |
|---|---|---|
| `*T` | pointer | one `T` |
| `[*]T` | pointer to many | the first of an unknown number of `T`; the only pointer that can be indexed (11.7) |
| `*[n]T` | pointer to array | an array of exactly `n` `T` (this is `*T` with `T = [n]T`) |
| `*opaque` | pointer to anything | memory of an unknown type |

`nullptr` is the pointer with address 0.

Pointers have no `+` or `-`. **Pointer arithmetic is indexing a pointer
to many:** `p[i]` is the `i`-th `T` after `p`: the offset `i` is
multiplied by the size of `T`, so the address is `p + i × @sizeof(T)`
(with `p: [*]int16`, `p[3]` is 6 bytes after `p`), and
`@ptr(p[i])` is that address as a `[*]T`, so `p = @ptr(p[1]);` steps to
the next element. A `*[n]T` converts to `[*]T` implicitly (8.2); a `*T`
does not, because it promises a single `T` (`@as([*]T)p` if needed).

### 5.4 Arrays

`[n]T` is `n` elements of type `T` stored one after another, without gaps.
`n` is a constant expression (8.4) of at least 1. An array is a **value**:
assignment and argument passing copy all elements, and two array types are
the same only if both length and element type are equal.

`[_]T` may be written only as the type of a variable that has an
initialiser; the length is taken from it (9.1).

There are no arrays of unknown length: a declaration always states the
length.

### 5.5 Structs and unions

```
struct{x: int16, y: int16}
union{word: uint16, bytes: [2]uint8}
```

- Fields are separated by commas; a trailing comma is allowed. A struct or
  union has at least one field, and field names in it are unique.
- **Struct:** fields in the written order, **no padding**; the size is the
  sum of the field sizes.
- **Union:** every field starts at offset 0; the size is that of the
  largest field.
- **Each written `struct{…}` or `union{…}` is a distinct type**, even if
  another one has the same fields. Use `type` to give it a name and refer to
  it in several places.

### 5.6 Function types

```
fn(int8, int8) returns int8        // parameter names are optional here
fn(a: int8, b: int8) returns int8
fn(c: char)                        // no result
```

A function type has no size (it is incomplete). Functions are reached by
name or through a pointer `*fn(…) returns …`, which is called like the
function itself (`f(x)`, 11.9) and cannot be dereferenced. Two function types are the
same if their parameter types and their result types are equal; parameter
names do not matter.

### 5.7 `opaque` and `type`

- `opaque` is "something of unknown type". It may only appear as
  `*opaque` (or behind further pointers).
- `type` is the type of type names. It exists only at compile time and
  appears in one place: `decl name: type;` (7.2).

### 5.8 Type syntax

A type is a sequence of prefixes followed by a base:

```
type    = { prefix } base ;
prefix  = "*" | "[" "*" "]" | "[" const_expr "]" | "[" "_" "]" ;
base    = int_type | "byte" | "char" | "addr" | "bool" | "opaque"
        | type_name | struct_type | union_type | fn_type ;
```

Read prefixes left to right:

| Written | Meaning |
|---|---|
| `[4]*int8` | array of 4 pointers to `int8` |
| `*[4]int8` | pointer to an array of 4 `int8` |
| `[3][4]int8` | array of 3 arrays of 4 `int8` |
| `[*]*char` | pointer to many pointers to `char` |
| `*fn(int8) returns int8` | pointer to a function |

### 5.9 Complete and incomplete types

A **complete** type has a known size, so values of it can be stored. All
types are complete except:

- function types,
- `opaque`,
- `type`,
- a type name declared with `decl name: type;` until its `type name = …`
  definition (7.2).

A value of an incomplete type cannot be created, stored, assigned, passed
or returned, and `@sizeof` of it is an error. A pointer to an incomplete
type is complete, but it cannot be dereferenced while its target is
incomplete.

---

## 6. Names and scopes

- **Declare before use.** Every name (variable, function, type) must be
  declared earlier in the file than its first use: by `decl`, `impl`, `var`
  or `type`. Two functions that call each other therefore need a `decl` for
  at least one of them.
- **One namespace** holds variables, functions and type names. Struct and
  union field names and loop names are separate (each per struct or union,
  each per function).
- **Scopes:** the file, the parameters and body of a function, and each
  block `{ … }`. A name is visible from its declaration to the end of its
  scope.
- **No shadowing.** A name may not be declared while another declaration of
  the same name is visible. A local variable or parameter may therefore not
  reuse the name of an earlier global, parameter or enclosing local.
- **No namespaces** yet; all exported names of a program share one space,
  and they are used unchanged as assembly labels.

---

## 7. Declarations

### 7.1 Top level

```
top_item = { attribute } ( decl | impl | var ) | type_def ;
```

### 7.2 `decl`: forward declaration and import

```
decl add: fn(int8, int8) returns int8;
decl table: [16]uint8;
decl first: [*]char;
decl user: type;
```

- `decl` states the type of a name without defining it. Its type may be any
  type, also an incomplete one. For a variable of an incomplete type only
  `@ptr(name)` is possible.
- If the same file later defines the name (`impl`, `var` or `type`), the
  definition must have **exactly the same type**. Otherwise the name is
  **imported**: another file must define and export it.
- A name may be declared with `decl` **only once** per file (after includes
  are expanded). Use include guards in headers.
- `decl` carries no linkage of its own: whether a later definition is
  exported is decided by the definition (`@internal` or not). A `decl` of a
  function that is `@recursive` must say so too: `@recursive decl f: fn(…);`.
- `decl name: type;` declares a type name that is incomplete until
  `type name = …;` follows. Types are never imported or exported: a type
  shared by several files is defined in a header.

### 7.3 `var`: variables

```
var count: uint8 = 0;
var buffer: [64]char = {0, _};
var greeting: [_]char = "Hello.";
@internal var state: bool = false;
var scratch: [256]uint8 = undefined;      // global only
```

- A variable always has an initial value. For a **global** variable it is a
  constant (8.4), an initialiser (9) or `undefined`; `undefined` leaves the
  contents unspecified. For a **local** variable it is any expression or
  initialiser of the type; `undefined` is not allowed.
- The type must be complete.
- A global variable is **exported** unless it is `@internal`.

### 7.4 `impl`: functions

```
impl add: fn(a: int8, b: int8) returns int8 {
    return a + b;
}
```

- The type after `:` is a function type in which every parameter has a
  name. The body is a block.
- `impl` declares the name from this point on; an earlier `decl` must
  match it exactly.
- A function is **exported** unless it is `@internal`.
- Parameters are local variables of the function, initialised with copies
  of the arguments; they may be assigned.
- `return expr;` ends the function with a result, `return;` without one.
  Whether every path ends with a `return` is **not checked**; falling off
  the end of a function that has a result type gives an unspecified result.
- **A function is not re-entrant unless it is `@recursive`** (7.7). A
  function that can be called again while it runs, directly (`f` calls
  `f`) or through other functions (`f` calls `g`, `g` calls `f`), must be
  marked `@recursive`, and so must every other function of such a cycle.
  **This is the programmer's responsibility**: the compiler does not check
  it, and a function without the mark that is re-entered behaves
  unpredictably (its parameters and locals are shared by all its calls).

### 7.5 `type`: type names

```
type point = struct{x: int16, y: int16};
type node = struct{value: int8, next: *node};    // the name is visible after '='
type handler = fn(c: char);
```

`type name = T;` makes `name` an **alias** for `T`: the two are the same
type. If `name` was declared with `decl name: type;`, it becomes complete
here.

### 7.6 `@internal`

`@internal` before `var` or `impl` (top level only) keeps the definition
local to its file: it is not exported. It is not allowed on `decl` or
`type`.

### 7.7 Attributes

Attributes are written before the declaration they apply to.

| Attribute | Applies to | Meaning |
|---|---|---|
| `@main` | `impl` | Marks the entry function of the program. At most one per file. Its required signature and how it is started will be defined with the calling convention. |
| `@section(name)` | `impl` | Places the code of the function in the named code section (`.code name` in assembly), for the linker script to place. |
| `@reg` | local `var` | Asks the compiler to keep the variable in a register if it can. `@ptr` of the variable is an error. |
| `@internal` | top-level `impl`, `var` | Not exported (7.6). |
| `@recursive` | `impl`, and the `decl` of a function | The function may be re-entered (7.4). A `decl` and the `impl` of the same function must agree. |

Several attributes may precede one declaration, in any order.

```
@section(isr)
impl handler: fn() { … }

@main
impl start: fn() { … }

@internal @recursive
impl walk: fn(n: *node) returns uint16 { … }
```

---

## 8. Conversions

### 8.1 Integer constants

An integer literal, a character literal, `@sizeof(T)`, and any constant
expression made of them (8.4) have **no fixed type**. A constant takes the
type that its context requires:

- the declared type of the variable it initialises or is assigned to,
- the parameter type when it is an argument, the result type in `return`,
- the type of the other operand of a binary operator,
- the element or field type inside an initialiser,
- `uint8` for a shift count,
- `uint16` for an index or a pointer offset (`int16` for a negative one).

The value must fit in that type, otherwise it is an error
(`var x: uint8 = 300;`, `var y: uint8 = -1;`). A constant never becomes
`bool` or a pointer.

### 8.2 Implicit conversions

Apart from integer constants, exactly these conversions happen without
being written:

| From | To |
|---|---|
| `*[n]T` | `[*]T` |
| `*[n]T` | `*T` (the address of the first element) |
| `[*]T` | `*T` |
| any pointer type | `*opaque` |
| any pointer type | `addr` (the address as a number) |
| `nullptr` | any pointer type |

A conversion is applied wherever a value of one type is used where another
type is required:

- **storing:** initialisation, assignment, an argument, a `return` value,
  an element or field in an initialiser;
- **inside operators:** when the operands of a comparison or of a
  dereference `[ ]` need it (8.3).

Since `addr` is `uint16` (5.1), a pointer converts to `uint16` as well, but
to no other integer type.

Everything else needs a builtin: `@cast` between integer types and between
integers and `bool`, `@as` for every other change, including pointer to
pointer in other directions, `addr` to pointer, and struct to struct.

### 8.3 Operands of operators

The two operands of a binary operator must have **the same type**, after
constants have taken their type (8.1) and after pointer conversions:

- **Comparison of two pointers** of different types: the operand whose type
  converts to the other's type (8.2) is converted. If neither converts
  (`*[4]int8` and `*[8]int8`, or `*int8` and `*int16`), it is an error.
- **Comparison of a pointer with an `addr`:** the pointer is converted to
  `addr`.
- **No pointer arithmetic with operators:** a pointer is never the left
  operand of an arithmetic or bit operator (`p + 1` is an error). A pointer
  moves by indexing a `[*]T` (11.7).
- **A pointer on the right** of an arithmetic or bit operator whose left
  operand is an `addr` is converted to `addr`, and the result is an `addr`:
  with `a: addr = p;` the distance `a - q` is a number of bytes.
- **Dereference** `[p]`: `[*]T` is converted to `*T`, so `[p]` of a pointer
  to many is its first element.
- **Indexing does not convert:** `x[i]` needs an array value or a `[*]T`.
  An element of an array behind `p: *[n]T` is written `[p][i]`.
- **Mixed integer widths or signedness** are not converted: `a + b` with
  `a: int8`, `b: int16` is an error; write `@cast(int16)a + b`.

### 8.4 Constant expressions

A constant expression is built from integer and character literals,
`@sizeof(T)`, aliases that expand to them, and the operators `+ - * / %
& | ^ ~ shl shr sar rol ror`. It is evaluated by the compiler exactly
(without wrapping); the final value must fit the type it takes (8.1).
`~`, `rol` and `ror` depend on a width, so they are evaluated in the type
the context gives; without one they are an error.

Constant expressions are required for array lengths and for the initial
values of global variables. A global initial value may also be `true`,
`false`, `nullptr`, `undefined`, a string literal, `s"…"`, `@ptr` of a
global variable or function, and an initialiser built from these.

---

## 9. Initialisers

An initialiser is a braced value of an array, struct or union. It may be
used wherever the expected type is known: in a variable declaration, on
the right of `=`, as an argument and after `return`.

### 9.1 Arrays

```
var a: [3]int8 = {1, 2, 3};
var b: [_]int8 = {1, 2, 3};          // [3]int8
var c: [64]uint8 = {0, _};           // 64 zeros
var d: [8]uint8 = {1, 2, 0xFF, _};   // 1, 2, then 0xFF up to the length
var m: [2][3]int8 = {{1, 2, 3}, {4, 5, 6}};
```

- Without `_`, there must be exactly `n` values.
- A final `_` repeats the value before it until the array has `n`
  elements (zero or more times). At least one value must precede it, and
  it may not be used with `[_]T`.
- A string literal initialises a `char` array; its length (including the
  zero byte) must equal the array length: `var s: [_]char = "Hi";` is
  `[3]char`.

### 9.2 Structs and unions

```
var p: point = {x = 3, y = 9};
var w: union{word: uint16, bytes: [2]uint8} = {word = 0x1234};
```

- A struct initialiser names **every field** exactly once, in any order.
- A union initialiser names **exactly one** field.

---

## 10. Statements

```
block      = "{" { statement } "}" ;
statement  = local_var | assignment | call_stmt | discard
           | if | loop | break | continue | return | block ;
```

There is no empty statement.

### 10.1 Local variables

`[@reg] var name: type = value;` as in 7.3. The variable lives until the end
of its block.

### 10.2 Assignment

```
x = 5;
[p].next = nullptr;
buffer[i] = 'a';
total += x;
```

- The left side is an **lvalue**: a variable, a dereference `[p]`, an
  element `x[i]` of an array lvalue or of a `[*]T`, or a field `s.f` of a
  struct or union lvalue.
- The right side converts to the type of the left (8.2). Arrays and structs
  are copied whole.
- `a op= b` means `a = a op b` with `a` evaluated once, for `op` in
  `+ - * / % & | ^`. The shift words have no compound form.
- Assignment is a statement, not an expression.

### 10.3 Calls and discarded results

```
uart_putc('x');            // a function without a result
_ = uart_getc();           // the result of a call must be used or discarded
```

- A call is a statement on its own only if the function has no result.
- `_ = expr;` evaluates `expr` and discards its value. It is required to
  ignore the result of a function.
- No other expression may stand alone as a statement.

### 10.4 `if`

```
if (a lt b) {
    …
} else if (a eq b) {
    …
} else {
    …
}
```

The condition is in parentheses and is a **condition** (Section 11.1). The
branches are blocks; `else if` is the only form allowed without braces.

### 10.5 `loop`, `break`, `continue`

```
loop {
    if (i ge n) { break; }
    i += 1;
}

loop outer {
    loop {
        if (done) { break outer; }
        continue outer;
    }
}
```

- `loop` is the only loop. It repeats its block until a `break` or a
  `return`.
- A loop may have a name, written after `loop`. `break name;` and
  `continue name;` refer to the enclosing loop of that name; without a name
  they refer to the innermost loop. Loop names are unique among the loops
  enclosing each other.
- `continue` starts the next pass of the loop.

### 10.6 `return`

`return expr;` in a function with a result type, `return;` in one without.

---

## 11. Expressions

### 11.1 Values and conditions

Y separates **values** (integers, `bool`, pointers, arrays, structs,
unions) from **conditions**. A condition is the result of a comparison, of
`not`, `and`, `or`, or a `bool` value used in a condition position.

- Conditions are allowed only in the parentheses of `if`, as operands of
  `not`, `and` and `or`, and inside `@bool( … )`.
- A `bool` value `b` in a condition position means `b eq true`.
- A condition is not a value: `var c: bool = a lt b;` is an error; write
  `@bool(a lt b)`.
- An integer or pointer is not a condition: write `x ne 0`,
  `p ne nullptr`.

### 11.2 Precedence

From highest to lowest. Operators of one level are evaluated **left to
right**: in `a | b & c` the `|` comes first.

| Level | Operators | Operands |
|---|---|---|
| 1 | `f(…)`, `x[i]`, `x.f` (postfix) | |
| 2 | `-x`, `~x`, `@as(T)x`, `@cast(T)x` (prefix) | |
| 3 | `&`, `\|`, `^`, `shl`, `shr`, `sar`, `rol`, `ror` | values |
| 4 | `*`, `/`, `%` | values |
| 5 | `+`, `-` | values |
| 6 | `eq`, `ne`, `lt`, `le`, `gt`, `ge` | values → condition |
| 7 | `not` | condition |
| 8 | `and`, `or` | conditions |

Consequences worth knowing:

- Bit operations bind tighter than arithmetic: `a + b & 0x0F` is
  `a + (b & 0x0F)`, and `x & 1 eq 0` is `(x & 1) eq 0`.
- `and` and `or` share a level: `a or b and c` is `(a or b) and c`.
- `not a eq b` is `not (a eq b)`.
- A comparison cannot be the operand of another comparison
  (`a lt b lt c` is an error, because a condition is not a value).
- Parentheses group as usual. `[ … ]` (dereference), `@ptr( … )`,
  `@sizeof( … )` and `@bool( … )` are primary expressions.

### 11.3 Arithmetic

`+ - * / %` and unary `-` work on integers of one type (8.3).

- All integer arithmetic **wraps** modulo 2⁸, 2¹⁶ or 2³² (also for signed
  types).
- `/` on signed integers rounds **toward zero**; `%` has the sign of the
  dividend; `a == (a / b) * b + a % b`. Division by zero is undefined.
- Unary `-` on an unsigned integer wraps (`-x` is `0 - x`).

### 11.4 Bit operations and shifts

- `&`, `|`, `^` work on two integers of one type, or on two `bool`s (the
  result is then a `bool`). `~x` inverts every bit of an integer; on a
  `bool` it gives the other value.
- Shifts: `x shl n`, `x shr n`, `x sar n`, `x rol n`, `x ror n`. `x` is an
  integer of any type, `n` an integer of an **unsigned** type of any width.
  The result has the type of `x`.

| Operator | Meaning | `n` ≥ width of `x` |
|---|---|---|
| `shl` | shift left, zeros in | 0 |
| `shr` | logical shift right, zeros in | 0 |
| `sar` | arithmetic shift right, sign bit kept | 0 or −1 (all ones) |
| `rol` | rotate left within the width of `x` | by `n` modulo the width |
| `ror` | rotate right within the width of `x` | by `n` modulo the width |

### 11.5 Comparisons

`eq ne lt le gt ge` compare two values of one type (8.3) and give a
condition.

- Integers: signed or unsigned order according to the type.
- `bool`: `eq` and `ne` only.
- Pointers: all six, comparing addresses as unsigned numbers.
- Arrays, structs and unions cannot be compared.

### 11.6 Logic

`not c`, `c1 and c2`, `c1 or c2` on conditions. `and` and `or`
**short-circuit**: the right operand is evaluated only if the left does not
decide the result.

### 11.7 Pointers

| Expression | Requires | Result |
|---|---|---|
| `@ptr(x)` | `x` is an lvalue or a function name | `*T`, `T` the type of `x` (`*[n]T` for an array, `*fn(…)` for a function); for an element `x[i]` a `[*]T`, see below |
| `[p]` | `p: *T` with complete `T` (`[*]T` converts, 8.3) | the lvalue `T` that `p` points to |
| `[p][i]` | `p: *[n]T` | element `i` of the array |
| `[p].f` | `p` points to a struct or union | field `f` |
| `x[i]` | `x: [*]T`, `i` an integer up to 16 bits (may be negative) | element `i`: the offset is multiplied by the size of `T`, so the `T` is at address `x + i × @sizeof(T)` |
| `@ptr(x[i])` | `x: [*]T`, or an array lvalue | the address of element `i` as a `[*]T` (which converts to `*T` where one is required): this is pointer arithmetic |
| `f(args)` | `f: *fn(…)` | a call through the pointer, written like a direct call; `[f]` is an error, because a function type is incomplete (5.9) |

Fields are reached through a pointer only by dereferencing first: `p.f` with
a pointer `p` is an error. Two pointers cannot be subtracted from each
other directly (`p - q` is an error); store one in an `addr` first, which is
implicit (8.2): `var a: addr = p;`, then `a - q` is the distance in bytes.

### 11.8 Arrays

`x[i]` on an array value `x: [n]T` gives element `i` (an lvalue if `x` is
one). The index is an integer of up to 16 bits. **Nothing is checked at run
time**; an index outside `0 … n−1` is undefined. A constant index outside
the range of an `[n]T` is a compile-time error.

### 11.9 Calls

`f(a, b)` calls the function named `f`, or, if `f` is a function pointer
(`*fn(…)`), the function it points to. A function pointer is called without
dereferencing it. The number of arguments must equal the number of
parameters, and each argument converts to its parameter type (8.2).
Arguments, including arrays and structs, are passed by value. The order in
which arguments are evaluated is unspecified.

### 11.10 Builtins

| Builtin | Meaning |
|---|---|
| `@bool(c)` | The logic expression `c` (a condition, 11.1) as a `bool`: `true` if it holds. An integer operand is an error; integers become `bool` only through `@cast(bool)x`. |
| `@sizeof(T)` | The size of the complete type `T` in bytes: a constant (8.1). Only a type is accepted, not an expression. |
| `@ptr(x)` | The address of `x` (11.7). |
| `@cast(T)x` | A **converted copy** of `x` (below). |
| `@as(T)x` | The bytes of `x` **reinterpreted** as `T`. Valid between any two types; nothing is checked. If the sizes differ, the result is defined by the implementation (for example, the bytes at the address of `x` read as a `T`, which may read or overwrite neighbouring memory). |

`@cast(T)x` conversions:

| From | To | Result |
|---|---|---|
| integer | wider integer | extended by the sign of the **source** type: sign extension from a signed type, zeros from an unsigned type |
| integer | narrower integer | the low bytes (wraps) |
| integer | integer of the same width | the same bits |
| integer | `bool` | `true` if `x` is not 0 |
| `bool` | integer | 1 or 0 |

Any other `@cast` is an error.

`@as(T)` and `@cast(T)` are prefix operators of level 2:
`@cast(int16)a + b` is `(@cast(int16)a) + b`, and `@as(*int8)p[i]`
reinterprets `p[i]`.

---

## 12. Programs

- A program is several `.y` and `.s` files, each translated separately and
  linked by `sra8-ld`.
- Every non-`@internal` `impl` and global `var` is exported under its own
  name; every name that is declared with `decl` but not defined in the file
  is imported. Types are not exported; headers (`.yh`) carry shared types
  and the `decl`s of exported names.
- Y names are the assembly label names, unchanged, so Y and assembly can
  refer to each other's symbols.

The compiler `ylangc` and the calling convention of its version 0.4 are
described in [ylangc.md](ylangc.md):

```
ylangc [-o out.s] [-I dir]... [-D NAME[=text]]... file.y
```

---

## 13. Not specified yet

- **The final calling convention (ABI).** [ylangc.md](ylangc.md) defines
  ABI 0.4, a simple one: a static frame per function, a stack frame for
  each call of a `@recursive` function, every register changed by a call.
  It will be replaced.
- **`@reg`**: ylangc does not support it yet.
- **Hardware access:** the UART port instructions (`ptr`, `ptw`),
  interrupt control (`intrr`, `intrw`, `psrw`), interrupt handlers (saving
  registers and leaving with `intrw #0`), inline assembly. `@section(isr)`
  only names a section; it does not make an interrupt handler.
- **`volatile`**: removed for now.
- **Generated headers:** the compiler may later write a `.yh` with the
  `decl`s of a file's exports.
- **The final keyword list** (4.3) and **namespaces** (6).

Not part of Y: `++` / `--`, constants other than `!DEFINE`, `static` local
variables (use a global), `while` / `for` / `do` / `switch` / `goto`, the
conditional operator, enums, floating point, variadic functions,
overloading, compound assignment of shifts.

---

## 14. Grammar

EBNF after preprocessing. `{ x }` is zero or more, `[ x ]` optional.
Terminals are quoted; `ident`, `int_lit`, `char_lit`, `string_lit` and
`sstring_lit` are the tokens of Section 4. Operator precedence is the table
of 11.2; the grammar below lists the forms only.

```
file          = { top_item } ;
top_item      = { attribute } ( decl | impl | var ) | type_def ;
attribute     = "@main" | "@section" "(" ident ")" | "@internal" | "@recursive" ;

decl          = "decl" ident ":" ( type | "type" ) ";" ;
type_def      = "type" ident "=" type ";" ;
impl          = "impl" ident ":" "fn" "(" [ param { "," param } [ "," ] ] ")"
                [ "returns" type ] block ;
param         = ident ":" type ;
var           = "var" ident ":" type "=" value ";" ;
value         = expr | init | "undefined" ;

type          = { prefix } base ;
prefix        = "*" | "[" "*" "]" | "[" ( expr | "_" ) "]" ;
base          = "int8" | "int16" | "int32" | "uint8" | "uint16" | "uint32"
              | "byte" | "char" | "addr" | "bool" | "opaque" | ident
              | ( "struct" | "union" ) "{" field { "," field } [ "," ] "}"
              | "fn" "(" [ fn_param { "," fn_param } [ "," ] ] ")" [ "returns" type ] ;
field         = ident ":" type ;
fn_param      = [ ident ":" ] type ;

block         = "{" { statement } "}" ;
statement     = [ "@reg" ] var
              | lvalue assign_op ( expr | init ) ";"
              | call ";"
              | "_" "=" expr ";"
              | if
              | "loop" [ ident ] block
              | "break" [ ident ] ";"
              | "continue" [ ident ] ";"
              | "return" [ expr | init ] ";"
              | block ;
assign_op     = "=" | "+=" | "-=" | "*=" | "/=" | "%=" | "&=" | "|=" | "^=" ;
if            = "if" "(" expr ")" block [ "else" ( if | block ) ] ;

expr          = expr binary_op expr
              | ( "-" | "~" | "not" ) expr
              | ( "@as" | "@cast" ) "(" type ")" expr
              | postfix ;
binary_op     = "and" | "or" | "eq" | "ne" | "lt" | "le" | "gt" | "ge"
              | "+" | "-" | "*" | "/" | "%"
              | "&" | "|" | "^" | "shl" | "shr" | "sar" | "rol" | "ror" ;
postfix       = primary { "(" [ arg { "," arg } ] ")" | "[" expr "]" | "." ident } ;
call          = postfix ;                      (* ending in an argument list *)
lvalue        = postfix ;                      (* see 10.2 *)
arg           = expr | init ;
primary       = int_lit | char_lit | string_lit | sstring_lit
              | "true" | "false" | "nullptr" | ident
              | "(" expr ")"
              | "[" expr "]"
              | "@ptr" "(" expr ")"
              | "@sizeof" "(" type ")"
              | "@bool" "(" expr ")" ;

init          = "{" ( init_list | field_list ) [ "," ] "}" ;
init_list     = elem { "," elem } [ "," "_" ] ;
elem          = expr | init ;
field_list    = ident "=" elem { "," ident "=" elem } ;
```

Types and expressions never appear in the same position: after `:`, after
`returns`, after the `=` of `type`, and inside `@sizeof( )`, `@as( )` and
`@cast( )` there is a type,
everywhere else an expression. `[` therefore starts an array or pointer
prefix in a type and a dereference in an expression, without ambiguity.

---

## 15. Example

```
!INCLUDE uart.yh

type line = struct{text: [32]char, length: uint8};

@internal var current: line = {text = {0, _}, length = 0};

// append c; false when the line is full
@internal impl append: fn(l: *line, c: char) returns bool {
    if ([l].length ge 31) {
        return false;
    }
    [l].text[[l].length] = c;
    [l].length += 1;
    [l].text[[l].length] = 0;        // keep the text zero-terminated
    return true;
}

impl print: fn(s: [*]char) {
    var i: uint16 = 0;
    loop {
        if (s[i] eq 0) { break; }
        uart_putc(s[i]);
        i += 1;
    }
}

@main
impl echo: fn() {
    print(s"ready\r\n");
    loop {
        var c: char = uart_getc();
        if (c eq '\r' or not append(@ptr(current), c)) {
            print(@ptr(current.text));
            current.length = 0;
            continue;
        }
        uart_putc(c);
    }
}
```

`uart.yh` here stands for a header that declares `uart_putc: fn(c: char)`
and `uart_getc: fn() returns char`; it does not exist yet (Section 13).

Points to note: `[l].text[[l].length]` indexes the array field of the
struct that `l` points to; `@ptr(current.text)` is a `*[32]char` that
converts to the parameter type `[*]char`; `not append(…)` uses the `bool`
result as a condition.
