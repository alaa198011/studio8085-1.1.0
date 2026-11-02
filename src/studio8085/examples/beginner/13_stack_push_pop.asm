; @title: The stack: PUSH and POP
; @topic: LXI SP, PUSH, POP, PUSH PSW
; @validation: T
;
; The stack is a pile of bytes in memory where programs park values.
;   PUSH rp  put a register pair on top of the pile (SP goes down by 2)
;   POP rp   take the top of the pile back into a register pair (SP goes up by 2)
; Last in, first out: the value pushed last is popped first.
;
; Switch to Advanced mode (toolbar) to see the Stack panel while you step.

        lxi   sp,2000h      ; choose where the stack lives
        lxi   b,1111h       ; BC = 1111h
        lxi   d,2222h       ; DE = 2222h
        push  b             ; pile: [1111h]
        push  d             ; pile: [2222h on top of 1111h]
        pop   b             ; BC = 2222h (the last value pushed)
        pop   d             ; DE = 1111h  -> the two pairs have swapped

; PUSH PSW saves A together with the flags. Handy to protect a value:
        mvi   a,7
        push  psw           ; save A (and the flags)
        xra   a             ; A = 0 (we have destroyed A)
        pop   psw           ; A = 7 again
        hlt
