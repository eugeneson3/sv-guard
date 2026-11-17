// Mistake 08: signal widths that do not match the port widths
//
// adder16 has 16-bit ports, but 8-bit signals are connected. The inputs are silently
// zero-extended and the 16-bit result is truncated to 8 bits, so the carry is lost.
// Fix: make the widths agree (or extend/slice explicitly so the intent is visible).
module adder16 (
    input  logic [15:0] a,
    input  logic [15:0] b,
    output logic [15:0] y
);
    assign y = a + b;
endmodule

module width_mismatch_bad (
    input  logic [7:0] x,
    input  logic [7:0] z,
    output logic [7:0] s
);
    adder16 u_add (
        .a(x),
        .b(z),
        .y(s)
    );
endmodule
