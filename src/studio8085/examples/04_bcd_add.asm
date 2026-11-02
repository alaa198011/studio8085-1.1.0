; @title: BCD addition
; @topic: DAA and the carry/auxiliary-carry flags
; @validation: T
;
; Decimal (BCD) addition with DAA.
;
; After ADI the accumulator holds a *binary* sum; DAA converts it back to two
; decimal digits. Step through (F11) and watch A, AC and CY.

        mvi   a,59h         ; 59 (BCD)
        adi   27h           ; + 27  -> 80h in binary...
        daa                 ; ...adjusted to 86h  (59 + 27 = 86)
        sta   result

        mvi   a,99h
        adi   01h           ; 9Ah
        daa                 ; 99 + 01 = 100 -> A = 00h, CY = 1, Z = 1
        sta   result+1
        hlt

result: ds    2
