
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
        +, -, &, |, ~, <<, >>,
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
        type
        types declared with decl
   */

   /* Type conversions
    Automatic:
        structs and unions with same types but different labels convert automatically
        *[n]T to *[]T to [*]T to *T
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

}


// This is a function implementation
// Implemented functiuon does not have to be forward declared, implementation will declare it as well. Forward declaration and implementation have to match
// Every implemented function is automatically exported
impl add: fn(a: int8, b: int8) returns int8 {

    var result: int8 = a + b;

    return result;
}

impl max: fn(a: int8, b: int8) returns int8 {
    @bool()
    if (a sm b) {
        return b;
    } else {
        return a;
    }
}


// internal keyword avoids exporting this function. it is only accessible in this file
internal impl helper: fn(a: int8) returns int8 {

}