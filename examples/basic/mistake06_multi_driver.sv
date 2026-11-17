// Mistake 06: one signal driven from two always blocks
//
// Each always_ff block is its own piece of hardware; two of them driving `flag` is a
// short circuit between two flip-flops. Simulation picks whichever runs last.
// Fix: drive flag from a single block, e.g.
//   always_ff @(posedge clk) if (set) flag <= 1'b1; else if (clr) flag <= 1'b0;
module multi_driver_bad (
    input  logic clk,
    input  logic set,
    input  logic clr,
    output logic flag
);
    always_ff @(posedge clk)
        if (set) flag <= 1'b1;

    always_ff @(posedge clk)
        if (clr) flag <= 1'b0;
endmodule
