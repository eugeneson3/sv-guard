// Intentionally buggy sample for Step 0 API exploration.
module sub (
    input  logic clk,
    input  logic a,
    output logic y
);
    assign y = a;
endmodule

module top (
    input  logic       clk,
    input  logic       rst_n,
    input  logic [1:0] sel,
    input  logic       d,
    output logic       q,
    output logic       z
);
    logic latch_out;
    logic r;

    // Latch: incomplete if inside always_comb
    always_comb begin
        if (sel == 2'b01)
            latch_out = d;
    end

    // Blocking assignment in always_ff
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) r = 1'b0;
        else        r = d;
    end

    // Nonblocking assignment in always_comb
    always_comb begin
        z <= latch_out;
    end

    // Unconnected input port 'a'
    sub u_sub (.clk(clk), .a(), .y(q));
endmodule
