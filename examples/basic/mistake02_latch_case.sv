// Mistake 02: `case` without `default` in always_comb -> latch
//
// sel == 2'b11 is not handled, so y keeps its old value in that case: a latch.
// Fix: add `default: y = '0;` (or assign y before the case).
module latch_case_bad (
    input  logic [1:0] sel,
    input  logic [7:0] a,
    input  logic [7:0] b,
    input  logic [7:0] c,
    output logic [7:0] y
);
    always_comb begin
        case (sel)
            2'b00: y = a;
            2'b01: y = b;
            2'b10: y = c;
        endcase
    end
endmodule
