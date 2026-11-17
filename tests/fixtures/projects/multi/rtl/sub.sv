module sub
    import types_pkg::*;
(
    input  logic  clk,
    input  data_t d,
    output data_t q
);
    always_ff @(posedge clk) q <= d;
endmodule
