// Reference: the same ideas written correctly. svguard should report nothing here.
//  - combinational logic: always_comb, blocking `=`, every output assigned on every path
//  - sequential logic: always_ff, nonblocking `<=`, one driver per signal
//  - every case has a default, every port is connected with the right width
module good_reference (
    input  logic       clk,
    input  logic       rst_n,
    input  logic [1:0] sel,
    input  logic [7:0] a,
    input  logic [7:0] b,
    output logic [7:0] y,
    output logic [7:0] q2
);
    logic [7:0] q1;

    always_comb begin
        y = '0;  // default first: no latch possible
        case (sel)
            2'b00:   y = a;
            2'b01:   y = b;
            default: y = a ^ b;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            q1 <= '0;
            q2 <= '0;
        end else begin
            q1 <= y;
            q2 <= q1;  // a real 2-stage pipeline thanks to `<=`
        end
    end
endmodule
