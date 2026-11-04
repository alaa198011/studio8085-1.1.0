; @title: Seven-segment display - raw segment bits
; @topic: OUT to a display; one bit per segment (Virtual 8085 Trainer Kit)
; @validation: T
; @display: raw
;
; Raw segment bits mode (the default), active-high: a 1 bit lights its segment.
;
;      aaa          bit:  7  6  5  4  3  2  1  0
;     f   b         seg:  DP g  f  e  d  c  b  a
;      ggg
;     e   c         76H = 0111 0110b -> b c e f g      = the letter H
;      ddd  DP      F6H = 1111 0110b -> b c e f g + DP = "H."
;
; The same byte also goes to the LEDs, so LEDn shows the bit that drives each segment.

START: MVI A,76H        ; the letter H
       OUT 02H          ; seven-segment display
       OUT 01H          ; LEDs: the same bits
       MVI A,0F6H       ; H with the decimal point (bit 7)
       OUT 02H
       OUT 01H
       HLT
