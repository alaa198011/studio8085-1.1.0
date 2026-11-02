; @title: A simple subroutine
; @topic: CALL and RET
; @validation: T
;
; A subroutine is a piece of code you can use many times.
;   CALL name  remembers where it came from (pushes the return address on the
;              stack), then jumps to name
;   RET        jumps back to the instruction after the CALL
;
; Step Into (F11) on a CALL to go inside. Step Over (F10) runs the whole
; subroutine in one go. Step Out (Shift+F11) finishes it and comes back.

        mvi   a,3
        call  double        ; A = 6
        call  double        ; A = 12
        call  double        ; A = 24
        hlt

double: add   a             ; A = A + A
        ret                 ; go back to just after the CALL that brought us here

; Try it: write a second subroutine that adds 10, and call it between the doubles.
