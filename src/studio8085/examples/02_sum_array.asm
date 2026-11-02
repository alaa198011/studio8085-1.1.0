; @title: Sum of an array
; @topic: Register pairs, carry into a 16-bit total
; @validation: T
;
; Add up 8 bytes into a 16-bit total (the sum does not fit in one byte).
; Result: the word at "total" (low byte first) and in HL.
; Demonstrates LXI, MOV A,M, the carry flag and 16-bit results.

        lxi   h,data        ; HL points at the first byte
        mvi   c,count       ; loop counter
        lxi   d,0           ; DE = 16-bit running total
sum:    mov   a,e
        add   m             ; add the next byte to the low half
        mov   e,a
        jnc   nocarry
        inr   d             ; carry out of the low byte -> bump the high byte
nocarry:
        inx   h
        dcr   c
        jnz   sum
        xchg                ; DE -> HL
        shld  total
        hlt

count:  equ   8
data:   db    200, 150, 100, 250, 255, 1, 2, 3
total:  ds    2
