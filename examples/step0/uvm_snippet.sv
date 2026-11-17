`include "uvm_macros.svh"
import uvm_pkg::*;
class my_driver extends uvm_driver;
    function new(string name, uvm_component parent);
        // missing super.new
    endfunction
    task run_phase(uvm_phase phase);
    endtask
endclass
