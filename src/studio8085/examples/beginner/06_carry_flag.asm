; @title: The carry flag
; @topic: ADD overflow, ADC for 16-bit addition, STC and CMC
; @validation: T
;
; An 8-bit register holds 0 to 255. Add 1 to 255 and the answer (256) does not
; fit: the register wraps to 00h and the CARRY flag (CY) becomes 1.
;
; Predict A, CY and Z before each step, then step and compare.

        mvi   a,0FFh        ; A = 255
        adi   01h           ; 255 + 1 = 256: A = 00h, CY = 1, Z = 1

; CY lets you add numbers bigger than 8 bits, one byte at a time.
; ADC adds the carry too ("Add with Carry"). Add 01FFh + 0001h:
        mvi   a,0FFh        ; low byte of the first number
        adi   01h           ; low bytes: FFh + 01h = 00h with CY = 1
        mov   l,a           ; L = 00h
        mvi   a,01h         ; high byte of the first number
        mvi   b,00h         ; high byte of the second number
        adc   b             ; A = 01h + 00h + CY(1) = 02h
        mov   h,a           ; H = 02h, so HL = 0200h = 01FFh + 0001h

; STC sets the carry flag, CMC flips it. Watch CY.
        stc                 ; CY = 1
        cmc                 ; CY = 0
        hlt
