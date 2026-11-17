module top
    import types_pkg::*;
(
    input  logic  clk,
    input  data_t din,
    output data_t dout
);
    sub u_sub (.clk(clk), .d(din), .q(dout));
endmodule
