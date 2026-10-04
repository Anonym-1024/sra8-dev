; The Y language (docs/y.md)

(comment) @comment

["decl" "impl" "var" "type" "returns"] @keyword
["struct" "union" "fn"] @keyword
["if" "else" "loop" "return" "break" "continue"] @keyword

; the word operators in bold and in one colour: every Zed theme draws
; emphasis.strong bold
["eq" "ne" "lt" "le" "gt" "ge" "not" "and" "or" "shl" "shr" "sar" "rol" "ror"] @emphasis.strong

(primitive_type) @type.builtin
(type_identifier) @type

(declaration name: (identifier) @function type: (function_type))
(declaration name: (identifier) @type type: "type")
(declaration name: (identifier) @variable
  type: [(primitive_type) (type_identifier) (pointer_type) (many_pointer_type) (array_type) (struct_type) (union_type)])
(implementation name: (identifier) @function)
(type_definition name: (identifier) @type)
(variable_declaration name: (identifier) @variable)
(parameter name: (identifier) @variable.parameter)
(field_declaration name: (identifier) @property)
(field_initializer name: (identifier) @property)
(member_expression field: (identifier) @property)
(call_expression function: (identifier) @function)
(loop_statement name: (identifier) @label)
(break_statement label: (identifier) @label)
(continue_statement label: (identifier) @label)

; builtins and attributes
["@ptr" "@sizeof" "@bool" "@as" "@cast"] @function.builtin
["@main" "@reg" "@section" "@internal" "@recursive"] @attribute
(attribute name: (identifier) @attribute)

(number) @number
(char) @string.special
(string) @string
(static_string) @string
[(true) (false)] @boolean
[(nullptr) "undefined"] @constant.builtin
[(fill) "_"] @variable.special

; the preprocessor: alias uses look like !DEFINE itself
["!INCLUDE" "!DEFINE" "!IFDEF" "!IFNDEF" "!ELSE" "IFDEF" "IFNDEF"] @preproc
(preproc_endif) @preproc
(alias) @preproc
(preproc_define name: (identifier) @constant)
(preproc_conditional name: (identifier) @constant)
(preproc_else name: (identifier) @constant)
(path) @string.special.path

["=" "+=" "-=" "*=" "/=" "%=" "&=" "|=" "^=" "+" "-" "*" "/" "%" "&" "|" "^" "~"] @operator
["(" ")" "[" "]" "{" "}"] @punctuation.bracket
["," ";" ":" "."] @punctuation.delimiter
