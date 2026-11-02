; @title: Interrupts
; @topic: TRAP, RST 7.5, SIM, EI, HLT
; @validation: T
;
; Interrupts. Run the program: it enables RST 7.5 and then sleeps on HLT.
; Open the Interrupts panel and press "RST 7.5" (maskable) or "TRAP" (not
; maskable). Each press runs the handler, which counts presses and shows the
; count on port 01h, then returns to the sleeping loop.
;
; RST 7.5 is masked after reset, so main unmasks it with SIM and then uses EI.

        org   0
        jmp   main

        org   24h           ; TRAP vector
trap:   lxi   h,traps
        inr   m
        ei
        ret

        org   3Ch           ; RST 7.5 vector
rst75:  lxi   h,presses
        inr   m
        mov   a,m
        out   01h           ; show the count
        ei                  ; an interrupt disables further ones; re-enable before returning
        ret

        org   100h
main:   lxi   sp,0FFFFh
        mvi   a,0Bh         ; SIM: bit 3 = change masks, bit 2 = 0 -> unmask RST 7.5
        sim
        ei
wait:   hlt                 ; sleep until an interrupt arrives
        jmp   wait

presses: ds   1
traps:   ds   1
