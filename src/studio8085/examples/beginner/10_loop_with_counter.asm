; @title: A loop with a counter
; @topic: DCR + JNZ - repeating instructions
; @validation: T
;
; A loop repeats instructions. The classic pattern:
;   1. put a count in a register,
;   2. do the work,
;   3. DCR the counter - this sets Z when it reaches 0,
;   4. JNZ ("jump if not zero") back to the start while Z is still 0.
;
; This program adds 10 + 9 + 8 + ... + 1.
; Tip: set a breakpoint on the "again" line (click in the gutter), press Run,
; and press Run again to go round one lap at a time.

        mvi   a,0           ; A = running total
        mvi   c,10          ; C = counter, and also the number we add each lap
again:  add   c             ; total = total + C
        dcr   c             ; C = C - 1   (Z = 1 when C reaches 0)
        jnz   again         ; not zero yet? go round again
        sta   total         ; finished: A = 55
        hlt

total:  ds    1

; Try it: how many instructions ran? The Flags/Status panel counts them.
