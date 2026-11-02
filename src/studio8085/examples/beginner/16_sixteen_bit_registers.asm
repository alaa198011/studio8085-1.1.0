; @title: 16-bit register pairs
; @topic: LXI, DAD, XCHG, INX, DCX
; @validation: T
;
; B-C, D-E and H-L can each be used as one 16-bit register (a "pair").
;   LXI rp,nn   load a 16-bit constant into a pair
;   DAD rp      HL = HL + rp   (a 16-bit add; only CY can change)
;   XCHG        swap HL and DE
;   INX / DCX   add / subtract 1 from a pair (no flags change)

        lxi   h,1000h       ; HL = 1000h
        lxi   d,0234h       ; DE = 0234h
        dad   d             ; HL = 1000h + 0234h = 1234h
        xchg                ; swap: HL = 0234h, DE = 1234h
        inx   d             ; DE = 1235h
        dcx   h             ; HL = 0233h
        hlt

; Watch the pair rows (BC, DE, HL) in the Registers panel.
; Try it: DAD sets CY when the 16-bit sum is bigger than FFFFh. Make HL = F000h and
; add 2000h to see it.
