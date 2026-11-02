; @title: Subtracting, and what "borrow" means
; @topic: SUB, SUI and the carry flag as a borrow
; @validation: T
;
;   SUB r   A = A - r          SUI n   A = A - n
;
; The 8085 has no negative-number type. If you subtract a bigger number from a
; smaller one the result wraps around (256 is added) and the CARRY flag (CY)
; is set to 1 to say "a borrow was needed".
;
; Predict each answer BEFORE you step. (Tick "Predict first" in the Explain panel.)

        mvi   a,50
        mvi   b,18
        sub   b             ; A = 50 - 18 = 32, CY = 0 (no borrow)
        sta   diff          ; keep the answer

        mvi   a,5
        sui   10            ; 5 - 10 = -5, which wraps to 251 (FBh). CY = 1: borrow!
        sta   diff+1        ; keep this answer in the next byte
        hlt

diff:   ds    2             ; two bytes for the two answers

; Note: FBh is how this processor writes -5 (two's complement): 256 - 5 = 251.
