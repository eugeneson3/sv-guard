// Mistake 05: blocking and nonblocking assignments mixed in one clocked block
//
// dout is assigned with `=` in the reset branch and with `<=` in the other branch,
// and prev reads dout with `=` - whether it sees the old or the new value depends on
// statement order. Simulation becomes order-dependent and hard to reason about.
// Fix: in a clocked block use `<=` for every assignment (and prefer always_ff).
module mixed_assign_bad (
    input  logic       clk,
    input  logic       rst_n,
    input  logic [7:0] din,
    output logic [7:0] dout,
    output logic [7:0] prev
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            dout = '0;
            prev <= '0;
        end else begin
            prev = dout;
            dout <= din;
        end
    end
endmodule
