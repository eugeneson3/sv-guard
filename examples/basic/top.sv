// Demo of common beginner mistakes. Step 1 reports what slang finds;
// the commented ones are caught by svguard's own rules from Step 5 on.
module top (
    input  logic       clk,
    input  logic       rst_n,
    input  logic [1:0] mode,
    input  logic       d,
    output logic [7:0] count,
    output logic       q
);
    logic hold;

    // Mistake 1: incomplete if in always_comb -> latch
    always_comb begin
        if (mode == 2'b01)
            hold = d;
    end

    // Mistake 2 (Step 5, SVG-C002): blocking '=' in always_ff
    always_ff @(posedge clk) begin
        q = hold;
    end

    // Mistake 3: input port left explicitly unconnected
    counter u_counter (
        .clk  (clk),
        .rst_n(rst_n),
        .en   (),
        .count(count)
    );
endmodule
