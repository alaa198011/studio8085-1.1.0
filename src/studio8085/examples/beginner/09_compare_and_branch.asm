; @title: Making a decision
; @topic: CPI and the conditional jumps JZ, JC, JMP
; @validation: T
;
; A program makes decisions by comparing, then jumping depending on the flags.
;   CPI n    compares A with n by subtracting, but throws the answer away:
;            only the flags change.  Z = 1 if equal,  CY = 1 if A is smaller.
;   JZ lab   jump to lab if Z = 1        JC lab   jump to lab if CY = 1
;   JMP lab  always jump
;
; This program puts a code in B:  1 = A below 10,  2 = A equal to 10,  3 = above 10.
; Predict B first, then run. Change the 7 and run again (Restart: Ctrl+Shift+F5).

        mvi   a,7           ; <- the number to test
        cpi   10            ; compare A with 10
        jz    equal         ; Z = 1  -> they are equal
        jc    smaller       ; CY = 1 -> A is smaller than 10

        mvi   b,3           ; neither: A is bigger
        jmp   done

equal:  mvi   b,2
        jmp   done

smaller: mvi  b,1

done:   hlt                 ; all three paths end here
