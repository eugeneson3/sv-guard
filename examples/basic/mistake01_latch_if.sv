// Mistake 01: incomplete `if` in always_comb -> latch
//
// When en == 0 nothing assigns q, so the hardware has to remember the old value.
// Synthesis builds a latch instead of combinational logic.
// Fix: add `else q = '0;`, or give q a default value before the if.
module latch_if_bad (
    input  logic       en,
    input  logic [7:0] d,
    output logic [7:0] q
);
    always_comb begin
        if (en)
            q = d;
    end
endmodule
