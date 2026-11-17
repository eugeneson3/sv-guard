// Mistake 04: nonblocking `<=` in always_comb
//
// `<=` updates happen at the end of the time step, so `zero` reads the OLD sum in
// simulation and needs an extra pass to settle. Synthesis does not care, so simulation
// and hardware can disagree.
// Fix: use blocking `=` in combinational logic.
module comb_nonblocking_bad (
    input  logic [3:0] a,
    input  logic [3:0] b,
    output logic [4:0] sum,
    output logic       zero
);
    always_comb begin
        sum  <= a + b;
        zero <= (sum == 5'd0);
    end
endmodule
