module latch (
    input  logic [1:0] sel,
    input  logic       d,
    output logic       q
);
    always_comb begin
        if (sel == 2'b01)
            q = d;
    end
endmodule
