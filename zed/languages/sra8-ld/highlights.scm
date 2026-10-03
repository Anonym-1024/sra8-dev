; sra8-ld linker scripts (docs/ld.md)

(comment) @comment
["memory" "place" "end" "symbol"] @keyword
["start" "size" "last" "align"] @keyword
["code" "data" "bss"] @type
(memory name: (identifier) @type)
(place region: (identifier) @type)
(symbol_definition region: (identifier) @type)
(section name: (identifier) @constant)
(symbol_here name: (identifier) @variable)
(symbol_definition name: (identifier) @variable)
(number) @number
["*" "="] @operator
