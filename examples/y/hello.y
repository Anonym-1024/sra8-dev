// hello.y -- greets, then echoes what it receives over the UART.
// Build: make -C examples   (links with uart.s and ldscripts/boot.ld)

!INCLUDE uart.yh

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
    print(s"Y says hello\r\n");
    loop {
        var c: char = uart_getc();
        if (c eq '\r') {
            print(s"\r\n");
        } else {
            uart_putc(c);
        }
    }
}
