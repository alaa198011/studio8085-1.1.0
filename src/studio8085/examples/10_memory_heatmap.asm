; @title: Fill and copy a memory page
; @topic: Block moves and the memory heatmap
; @validation: T
;
; Fill one 256-byte page, then copy it to another page.
;
; Open the Memory panel, choose a slow speed and press Run: the first page
; lights up as it is written (orange), then both pages flash as they are
; copied (blue = read, orange = written). Try "Access frequency" mode afterwards.

        lxi   h,source
        mvi   b,0           ; B = value and counter
fill:   mov   m,b           ; source[i] = i
        inx   h
        inr   b
        jnz   fill          ; 256 iterations

        lxi   h,source
        lxi   d,dest
        mvi   b,0
copy:   mov   a,m
        stax  d
        inx   h
        inx   d
        dcr   b
        jnz   copy
        hlt

        org   2000h
source: ds    256
        org   3000h
dest:   ds    256
