; @title: 8 x 8 multiplication
; @topic: Shift-and-add, RAR, DAD
; @validation: T
;
; 8 x 8 -> 16-bit multiplication by shift-and-add.
; Result: HL, also stored at "product".  13 x 17 = 221 = 00DDh.
; Change the two MVI values to try other numbers.

        mvi   a,13          ; multiplier
        mvi   e,17          ; multiplicand ...
        mvi   d,0           ; ... widened to 16 bits in DE
        lxi   h,0           ; HL = product so far
        mvi   b,8           ; one step per bit of the multiplier
mloop:  rar                 ; next multiplier bit -> carry
        jnc   skip
        dad   d             ; bit set: product += multiplicand
skip:   xchg                ; multiplicand <<= 1, using HL as scratch
        dad   h
        xchg
        dcr   b
        jnz   mloop
        shld  product
        hlt

product: ds   2
