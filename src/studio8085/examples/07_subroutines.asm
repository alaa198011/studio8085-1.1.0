; @title: Subroutines and the stack
; @topic: CALL, RET, PUSH, POP, nested calls
; @validation: T
;
; Subroutines and the stack.
;
; * F11 (Step Into) on a CALL enters the routine; Shift+F11 (Step Out) runs until it returns.
; * F10 (Step Over) runs the whole routine in one go.
; * Watch the Stack panel: each CALL pushes a 2-byte return address,
;   and the "Points to" column names where it will return.

        lxi   sp,8000h
        mvi   a,3
        call  square        ; A = 3 x 3 = 9
        call  square        ; A = 9 x 9 = 81
        sta   result
        call  outer         ; nested calls
        hlt

square: push  b             ; preserve BC for the caller
        mov   b,a
        mov   c,a
        xra   a
sqloop: add   b             ; A = A + B, repeated C times
        dcr   c
        jnz   sqloop
        pop   b
        ret

outer:  mvi   a,1
        call  inner         ; the stack grows by two more bytes here
        inr   a
        ret

inner:  inr   a
        ret

result: ds    1
