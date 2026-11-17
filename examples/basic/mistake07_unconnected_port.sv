// Mistake 07: instance ports left unconnected
//
// `.en()` is explicitly empty, so en floats (z / x in simulation) and the counter never
// counts as intended. The second instance forgets rst_n completely.
// Fix: connect every input port (tie unused ones to a constant on purpose).
module up_counter8 (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       en,
    output logic [7:0] count
);
    always_ff @(posedge clk or negedge rst_n)
        if (!rst_n)  count <= '0;
        else if (en) count <= count + 8'd1;
endmodule

module unconnected_port_bad (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       enable,
    output logic [7:0] value_a,
    output logic [7:0] value_b
);
    up_counter8 u_cnt_a (
        .clk  (clk),
        .rst_n(rst_n),
        .en   (),
        .count(value_a)
    );

    up_counter8 u_cnt_b (
        .clk  (clk),
        .en   (enable),
        .count(value_b)
    );
endmodule
