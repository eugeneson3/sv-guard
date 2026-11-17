module syntax_error (
    input  logic a,
    output logic y
);
    assign y = a   // missing semicolon
endmodule
