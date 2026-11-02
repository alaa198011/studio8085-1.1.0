; @title: Fibonacci numbers
; @topic: Register rotation and memory stores
; @validation: T
;
; The first 13 Fibonacci numbers (all fit in a byte), stored at "series".
; Watch the stores light up in the Memory heatmap.

        lxi   h,series
        mvi   e,count       ; how many numbers to produce
        mvi   b,0           ; previous
        mvi   c,1           ; current
loop:   mov   m,b           ; store the previous number
        inx   h
        mov   a,b
        add   c             ; next = previous + current
        mov   b,c
        mov   c,a
        dcr   e
        jnz   loop
        hlt

count:  equ   13
series: ds    count
