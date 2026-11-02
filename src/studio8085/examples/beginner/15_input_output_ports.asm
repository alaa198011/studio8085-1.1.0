; @title: Input and output ports
; @topic: IN and OUT
; @validation: T
;
; Ports are how a processor talks to the outside world (switches, lamps, displays).
;   IN port    read the port into A
;   OUT port   write A to the port
;
; Here there is no real hardware, so the I/O Ports panel stands in for it:
;   * type a value for port 00h in the I/O Ports panel BEFORE you run (this is the "switches"),
;   * after the run, port 01h shows what the program sent out (the "lamps"),
;     and the Output panel logs every OUT.

        in    00h           ; A = whatever you typed for port 00h (0 if you typed nothing)
        adi   1             ; add one
        out   01h           ; show the answer on port 01h
        hlt

; Try it: put 41h on port 00h and run - port 01h should show 42h.
