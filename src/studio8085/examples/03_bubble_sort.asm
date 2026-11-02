; @title: Bubble sort
; @topic: Memory addressing, CMP and conditional jumps
; @validation: T
;
; Bubble sort 8 bytes into ascending order. Correct with duplicate values.
;
; Tip: click in the gutter next to "swap" to set a breakpoint, press Run (F5),
; and watch the bytes of "list" being rearranged in the Symbols panel.

sort:   lxi   h,list
        mvi   d,0           ; D = 1 when this pass swapped something
        mvi   c,count-1     ; comparisons per pass
pass:   mov   a,m           ; A = list[i]
        inx   h
        cmp   m             ; compare with list[i+1]
        jc    ok            ; A < next : already in order
        jz    ok            ; A = next : already in order
swap:   mov   b,m           ; exchange the two neighbours
        mov   m,a
        dcx   h
        mov   m,b
        inx   h
        mvi   d,1
ok:     dcr   c
        jnz   pass
        mov   a,d
        ana   a             ; set Z from D
        jnz   sort          ; something moved: do another pass
        hlt

count:  equ   8
list:   db    42, 7, 19, 7, 255, 0, 63, 1
