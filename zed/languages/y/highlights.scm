; The Y language (examples/asm/echo.y)

(comment) @comment

["decl" "impl" "var" "type" "internal" "returns"] @keyword
["struct" "union" "fn"] @keyword
["if" "else" "while" "do" "for" "return" "break" "continue" "goto" "switch" "case" "default"] @keyword

; the logic operators in bold: every Zed theme draws emphasis.strong bold
["eq" "neq" "gt" "sm" "gte" "sme" "not" "and" "or"] @emphasis.strong

(primitive_type) @type.builtin
(type_identifier) @type

(declaration name: (identifier) @function type: (function_type))
(declaration name: (identifier) @type type: (type_type))
(declaration name: (identifier) @variable
  type: [(primitive_type) (type_identifier) (pointer_type) (many_pointer_type) (array_type) (struct_type) (union_type)])
(implementation name: (identifier) @function)
(type_definition name: (identifier) @type)
(variable_declaration name: (identifier) @variable)
(for_variable name: (identifier) @variable)
(parameter name: (identifier) @variable.parameter)
(field_declaration name: (identifier) @property)
(member_expression field: (identifier) @property)
(call_expression function: (identifier) @function)
(builtin) @function.builtin
(goto_statement label: (identifier) @label)

(number) @number
(char) @string.special
(string) @string
[(true) (false)] @boolean
(null) @constant.builtin

; the preprocessor: alias uses look like !DEFINE itself
["!INCLUDE" "!DEFINE" "!IFDEF" "!IFNDEF"] @preproc
[(preproc_else) (preproc_endif)] @preproc
(alias) @preproc
(preproc_define name: (identifier) @constant)
(preproc_conditional name: (identifier) @constant)
(path) @string.special.path

["=" "+" "-" "&" "|" "~" "<<" ">>" "*"] @operator
["(" ")" "[" "]" "{" "}"] @punctuation.bracket
["," ";" ":" "."] @punctuation.delimiter
