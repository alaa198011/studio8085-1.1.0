; @title: Moving data between registers
; @topic: MOV - copy, not move
; @validation: T
;
; MOV d,s copies the value in s into d. The source keeps its value, so the name
; "move" is a little misleading: it is really a copy.
;
; Watch the Registers panel after each step.

        mvi   d,42h         ; D = 42h
        mov   e,d           ; E = D  -> E = 42h, and D is still 42h

; Swapping two registers needs a third one to hold a value for a moment,
; like swapping two glasses of water using an empty glass.
        mvi   a,1           ; A = 1
        mvi   b,2           ; B = 2
        mov   c,a           ; C = A  (save A's value in C)
        mov   a,b           ; A = B  -> A = 2
        mov   b,c           ; B = C  -> B = 1
        hlt                 ; now A = 2 and B = 1: they have swapped

; Try it: what happens if you leave out the "mov c,a" line?
