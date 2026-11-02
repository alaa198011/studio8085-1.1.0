; @title: Counting up and down
; @topic: INR, DCR, INX and the zero flag
; @validation: T
;
;   INR r   add 1 to register r        DCR r   subtract 1 from register r
;   INX rp  add 1 to a register PAIR   (BC, DE or HL, 16 bits)
;
; INR and DCR set the zero flag (Z) when the result is 0 - the key to loops.
; They do NOT touch the carry flag (CY).

        mvi   b,0
        inr   b             ; B = 1
        inr   b             ; B = 2
        inr   b             ; B = 3

        mvi   c,3
        dcr   c             ; C = 2
        dcr   c             ; C = 1
        dcr   c             ; C = 0 and Z = 1  (watch the Z flag light up)

        lxi   h,00FFh       ; HL = 00FFh  (LXI loads a 16-bit constant into a pair)
        inx   h             ; HL = 0100h  (the carry from L moves into H)

        mvi   d,0FFh        ; D = 255, the biggest 8-bit number
        inr   d             ; 255 + 1 wraps to 00h. Z = 1 but CY stays 0!
        hlt

; Try it: INR never sets CY. Use ADI 1 instead of INR D and see CY become 1.
