module vendor_ip (input logic a, output logic y);
    assign y = a   // vendor code with an error: excluded via --exclude 'third_party/**'
endmodule
