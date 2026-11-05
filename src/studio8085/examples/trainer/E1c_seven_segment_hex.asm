; @title: Seven-segment display - hex decode from the switches
; @topic: IN, OUT and a hex-decoding display (Virtual 8085 Trainer Kit)
; @validation: T
; @display: hex
;
; Set the display to "Hex decode (low nibble)" (opening this lab from the Lab menu does it for you).
; In that mode bits 3-0 of the byte choose the digit 0-F and bits 7-4 are ignored.
;
; Try it: set SW3..SW0 to 1010 and run - the display shows A. Change the switches and Restart.

START: IN 00H           ; A <- the switches
       OUT 01H          ; the LEDs show the whole byte
       OUT 02H          ; the display shows the low nibble as a hex digit
       HLT
