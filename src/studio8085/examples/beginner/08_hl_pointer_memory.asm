; @title: HL as a memory pointer
; @topic: LXI H, the "M" register, MVI M, MOV A,M, INR M
; @validation: T
;
; The pair HL can hold a memory ADDRESS. The special name M then means
; "the memory byte that HL points to". This is how programs walk through lists.
;
; Step slowly and watch HL change in the Registers panel, and the bytes of
; "table" appear in the Memory panel.

        lxi   h,table       ; HL = the address of "table"
        mvi   m,11h         ; write 11h into the byte HL points to: table[0]
        inx   h             ; point at the next byte
        mvi   m,22h         ; table[1] = 22h
        inx   h             ; and the next
        mvi   m,33h         ; table[2] = 33h

        lxi   h,table+1     ; point at table[1] again ("table+1" = address + 1)
        mov   a,m           ; read it: A = 22h
        inr   m             ; add 1 to the memory byte itself: table[1] = 23h
        hlt

table:  ds    3             ; three bytes of storage

; Remember: M is not a real register - it is memory, reached through HL.
