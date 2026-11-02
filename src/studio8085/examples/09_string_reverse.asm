; @title: Reverse a string
; @topic: Two pointers, 16-bit compare, ASCII data
; @validation: T
;
; Reverse a string in place with two pointers that walk toward each other.
; Look at the ASCII column of the hex view (click "text" in the Symbols panel).

        lxi   h,text        ; HL -> first character
        lxi   d,text+len-1  ; DE -> last character
rev:    mov   a,e           ; 16-bit compare DE - HL ...
        sub   l
        mov   a,d
        sbb   h
        jc    done          ; ... carry means the pointers have crossed
        ldax  d             ; A = last
        mov   b,m           ; B = first
        mov   m,a           ; first = last
        mov   a,b
        stax  d             ; last = first
        inx   h
        dcx   d
        jmp   rev
done:   hlt

text:   db    "Hello, 8085!"
len:    equ   $-text        ; $ is the current address, so this is the string length
