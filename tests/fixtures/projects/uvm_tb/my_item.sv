class my_item extends uvm_sequence_item;
    rand bit [7:0] data;
    `uvm_object_utils(my_item)

    function new(string name = "my_item");
        super.new(name);
    endfunction
endclass
