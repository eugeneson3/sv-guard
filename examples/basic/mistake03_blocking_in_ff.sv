// Mistake 03: blocking `=` in a clocked block
//
// Intended: a 3-stage shift register (d -> q1 -> q2 -> q3, one stage per clock).
// With `=` the assignments run one after another within the same clock edge, so q3
// receives d right away: it behaves as a single flip-flop, and simulation may differ
// from synthesis.
// Fix: use nonblocking `<=` for every flip-flop.
module shift_blocking_bad (
    input  logic clk,
    input  logic d,
    output logic q3
);
    logic q1, q2;

    always_ff @(posedge clk) begin
        q1 = d;
        q2 = q1;
        q3 = q2;
    end
endmodule
