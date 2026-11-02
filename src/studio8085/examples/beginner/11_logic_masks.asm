; @title: Bits: AND, OR, XOR and complement
; @topic: ANI, ORI, XRI, CMA, XRA A
; @validation: T
;
; Logic instructions work on each bit separately. Watch the BINARY column
; of register A in the Registers panel.
;
;   ANI mask  keeps only the bits where mask has 1   (clears the others)
;   ORI mask  turns ON the bits where mask has 1
;   XRI mask  flips the bits where mask has 1
;   CMA       flips every bit of A

        mvi   a,0A5h        ; 1010 0101
        ani   0Fh           ; AND 0000 1111  -> 0000 0101 = 05h  (low 4 bits kept)
        mov   b,a           ; B = 05h

        mvi   a,0A0h        ; 1010 0000
        ori   05h           ; OR  0000 0101  -> 1010 0101 = A5h  (two bits set)
        mov   c,a           ; C = A5h

        mvi   a,0FFh        ; 1111 1111
        xri   0Fh           ; XOR 0000 1111  -> 1111 0000 = F0h  (low 4 bits flipped)
        mov   d,a           ; D = F0h

        mvi   a,0F0h        ; 1111 0000
        cma                 ; flip all bits -> 0000 1111 = 0Fh
        mov   e,a           ; E = 0Fh

        xra   a             ; A XOR A is always 0: the quickest way to clear A.
        hlt                 ; (It also sets Z = 1 and clears CY.)
