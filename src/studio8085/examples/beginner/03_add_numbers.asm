; @title: Adding numbers
; @topic: ADD, ADI and storing a result in memory with STA
; @validation: T
;
; Most arithmetic happens in register A, the accumulator.
;   ADD r   adds register r to A.
;   ADI n   adds the constant n to A ("Add Immediate").
;   STA addr stores A in the memory byte at address addr.
;
; Press F7, then step with F11. Watch A, and the Memory panel at the end.

        mvi   a,25          ; A = 25
        mvi   b,17          ; B = 17
        add   b             ; A = A + B = 42   (2Ah in hexadecimal)
        adi   8             ; A = A + 8 = 50   (32h)
        sta   result        ; copy A into the memory byte called "result"
        hlt

result: ds    1             ; reserve one byte of memory, named "result"

; Try it: click "result" in the Symbols panel (Advanced mode) to find the byte.
; The Registers panel shows the same value in hexadecimal, decimal and binary.
