; @title: Your first program
; @topic: MVI, NOP and HLT - the smallest useful program
; @validation: T
;
; Welcome! A program is a list of instructions. The processor runs them one at a time.
;
;   1. Press F7 (Assemble) - this turns the text into machine code.
;   2. Press F11 (Step) once per line and watch the Registers panel on the left.
;   3. The highlighted line is the NEXT instruction to run, not the one that just ran.
;
; MVI means "Move Immediate": put a constant straight into a register.
; Numbers are decimal unless they end in h (hexadecimal). A hex number that starts
; with a letter needs a leading 0, so write 0FFh, not FFh.

        mvi   a,5           ; A = 5
        mvi   b,10          ; B = 10 (decimal)
        mvi   c,0FFh        ; C = FFh = 255 (hexadecimal)
        nop                 ; NOP = "no operation": does nothing for 4 T-states
        hlt                 ; HLT stops the program. Every program needs one.

; Try it: change a number and press Restart (Ctrl+Shift+F5), then step again.
