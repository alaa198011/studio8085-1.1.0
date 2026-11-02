; @title: Counter on LEDs
; @topic: Loops, OUT, CALL/RET delay
; @validation: T
;
; Count from 0 to 255 on port 01h, as if it drove 8 LEDs.
;
; Try it: set the toolbar speed to "1,000 / s", press Run (F5) and watch
; port 01h change in the I/O Ports panel and the Output log.

        mvi   b,0           ; B = the counter
next:   mov   a,b
        out   01h           ; show it on the "LEDs"
        call  delay
        inr   b
        jnz   next          ; B wraps from 255 to 0, which ends the loop
        hlt

delay:  mvi   c,20          ; each pass of the loop costs DCR 4 + JNZ 10 = 14 T-states
dloop:  dcr   c
        jnz   dloop
        ret
