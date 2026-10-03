
/*
    Preprocessor
        !INCLUDE file.yh
        !DEFINE constant 0
        !constant
        !IFNDEF constant
        !ENDIF
*/

/* Primitive types
    basic numeric types.
    Defined operations
        = (assignment)
        +, -, *, / ,&, |, ~, <<, >>,
        eq, neq, gt, sm, gte, sme, not, and, or operators for logic operations that map to conditional execution in assembly
        @bool(condition-expression) builtin macro that will convert logic expression to 0 or 1.

    int8 ... uint32
    byte = uint8
    char = uint8
    bool = uint8
    addr = uint16
 */

 /* Compound types
    Types that combine more data types.

    struct{a: T1, b: T2} Backed by a frame containing the whole struct.
        operations defined on 'x: struct{a: T}'
            
            x.a evaluates to T
    union{a: T1, b: T2} Backed by the largest member type
        operations defined on 'x: union{a: T}'
            
            x.a evaluates to T
    fn(T1, T2) returns T3, returns clause is optional
        operations defined on 'x: fn(T) returns R'
                x(y) calls the function and evaluates to R
    *T - pointer to T. Backed by addr.

        operations defined on 'x: *T'
                [x] evaluates to T
                +- for pointer arithmetic, offset is measured in bytes
                [x +- n] for pointer arithmetic + dereferencing

    [*]T - Pointer to many T. Backed by addr.
        operations defined on 'x: [*]T'
                x[i] evaluates to T

    [n]T - Array of n items of type T. Backed by the whole array frame.
        operations defined on 'x: [n]T'
                x[i] evaluates to T

    []T - Array of unknown length
        operations defined on 'x: []T'
                x[i] evaluates to T


    
  */

  /* Complete vs incomplete types
    Complete types have a concrete size, can be store in memory.
    Incomplete types have an unknown size, cannot be assigned or passed as arguments.
    All types are complete except:
        fn(...) returns ...
        []T
        opaque
        type
        types declared with decl
   */

   /* Type conversions
    Automatic:
        *[n]T to [*]T to *T
        addr = uint16
        char = uint8 = byte
        ...
    */

    
    /*
        Type definitions

        decl user: type; symbol user is of type 'type' which is incomplete

        decl database: type;

        type user = struct{
            id: uint8
            dbptr: *database // pointer to incomplete type is allowed
        }

        //if i tried to dereference user.dbptr at this point it is a compile time error

        type database = struct { ... }

        // now database is no longer incomplete, so it can be dereferenced

        



    */

    /* Builtin macros
        @bool(logic-expr) converts logic to number
        @sizeof(T) return size of a complete type in bytes
        @as(T)x reinterprets type without changing the actual value. 
            var a: int8 = 9;
            var b: int32 = @as(int32)a; // this will corrupt memory since a is treated as 4 bytes when it actually is only one

            //can be used for ptr conversion or compatible types conversion (struct with same field etc)
            // compiler does not check for correctness
            decl a: *opaque;
            var b: int8 = [@as(*int8)a]
            var b: int8 = [a] // error since incomplete type 'opaque' cannot be dereferenced

        @cast(T)x creates a copy of the value while properly converting
            converting between integer types
            compiler will strictly define which conversions are valid
        
        @vol var ... marks variable as volatile
        @reg var ... tells the compiler to try to keep var in register if possible. Cannot take address of such variable
        
     */

    /*
        etc.
        The compiler should be able to compute constant expressions, so 4*@sizeof(int16)+1 is evaluated at compile time.
     */




// Declaration of symbols
// Serves both as forward declaration and import of symbols that are undefined in the file
// Multiple declarations of the same symbol is an error
// Declarations can be put into '.yh' header file.
// File can be included using !INCLUDE header.yh



decl add: fn(int8, int8) returns int8;
decl max: fn(int8, int8) returns int8;
decl helper: fn(int8) returns int8;

decl a: [*]int8



impl main: fn()
{
    
    var a: int8 = 8;
}


var x: bool = 0;

@section(isr)
impl isr: fn()
{
    x = 1;
    @reg var counter: int8 = 0;
}


// This is a function implementation
// Implemented functiuon does not have to be forward declared, implementation will declare it as well. Forward declaration and implementation have to match
// Every implemented function is automatically exported
impl add: fn(a: int8, b: int8) returns int8 {

    var result: int8 = a + b;

    return result;
}

impl max: fn(a: int8, b: int8) returns int8 {
    
    if (a lt b) {
        return b;
    } else {
        return a;
    }
}


// internal keyword avoids exporting this function. it is only accessible in this file
internal impl helper: fn(a: int8) returns int8 {

}