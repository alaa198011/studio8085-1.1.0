; @title: Rotating bits: doubling and halving
; @topic: RLC, RAR, ORA A and the carry flag
; @validation: T
;
; Rotating moves every bit of A one place.
;   RLC  rotate left:  A becomes A x 2 (for small numbers)
;   RAR  rotate right through the carry: A becomes A / 2, and the bit that
;        falls off the end lands in CY.
;
; Watch the BINARY column of A. Each rotate shifts the 1-bits one place.

        mvi   a,5           ; 0000 0101
        rlc                 ; 0000 1010 = 10  (doubled)
        rlc                 ; 0001 0100 = 20  (doubled again)
        mov   b,a           ; B = 20, kept for later

        ora   a             ; OR A with itself: A is unchanged but CY is cleared.
        rar                 ; 0000 1010 = 10  (halved)
        rar                 ; 0000 0101 = 5   (halved)
        rar                 ; 0000 0010 = 2   and the odd bit goes into CY = 1
        hlt                 ; 5 / 2 = 2 remainder 1: the remainder is in CY

; Try it: RAR also pulls the OLD carry in at the left. That is why ORA A
; (which clears CY) comes first.
