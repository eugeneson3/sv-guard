// Mistake 09: FSM `case` that forgets a state
//
// The case has no branch for DONE (and no default), so once the FSM reaches DONE
// `next` stays DONE forever: the machine is stuck.
// Fix: handle every state (DONE: next = IDLE;) and add a default.
module fsm_missing_state_bad (
    input  logic clk,
    input  logic rst_n,
    input  logic go,
    output logic busy
);
    typedef enum logic [1:0] {IDLE, RUN, DONE} state_t;
    state_t state, next;

    always_ff @(posedge clk or negedge rst_n)
        if (!rst_n) state <= IDLE;
        else        state <= next;

    always_comb begin
        next = state;
        busy = 1'b0;
        case (state)
            IDLE: if (go) next = RUN;
            RUN: begin
                busy = 1'b1;
                next = DONE;
            end
        endcase
    end
endmodule
