; SRA-8 assembly.  A label reference has the colour of its definition:
; =name like name:, .b =name / .f =name like .l name:

(comment) @comment

(label name: (identifier) @function)
(label_ref !direction name: (identifier) @function)
(local_label name: (identifier) @label)
(label_ref direction: _ name: (identifier) @label)
(local_label ".l" @keyword.modifier)
(label_ref direction: _ @keyword.modifier)

(instruction mnemonic: (identifier) @keyword)

((directive_name) @type
  (#match? @type "^\\.(byte|word|dword|qword|addr|ascii|asciz|res)$"))
((directive_name) @keyword.directive
  (#match? @keyword.directive "^\\.(code|data|bss|import|export)$"))

(directive (identifier) @constant)

(register) @variable.special
(number) @number
(char) @string.special
(string) @string

; the preprocessor: alias uses look like !DEFINE itself
["!INCLUDE" "!DEFINE"] @preproc
(alias) @preproc
(preproc_define name: (identifier) @constant)
(path) @string.special.path

["#" "=" "+" "-"] @operator
["," ":"] @punctuation.delimiter
