class my_driver extends uvm_driver #(my_item);
    `uvm_component_utils(my_driver)

    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction

    task run_phase(uvm_phase phase);
        forever begin
            seq_item_port.get_next_item(req);
            `uvm_info("DRV", $sformatf("data=%0h", req.data), UVM_LOW)
            seq_item_port.item_done();
        end
    endtask
endclass
