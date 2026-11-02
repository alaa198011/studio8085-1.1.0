; @title: Copying a list of bytes
; @topic: pointers, STAX, loops - putting it all together
; @validation: T
;
; Copy 5 bytes from "source" to "dest" with two pointers:
;   HL points at the byte to read      (MOV A,M)
;   DE points at where to write it     (STAX D)
; and a counter in C decides when to stop.
;
; This uses almost everything from the earlier examples. Step through one lap,
; then set a breakpoint on "copy" and let it run lap by lap.

        lxi   h,source      ; HL -> first byte to read
        lxi   d,dest        ; DE -> first place to write
        mvi   c,5           ; five bytes to copy
copy:   mov   a,m           ; A = the byte HL points at
        stax  d             ; write A where DE points
        inx   h             ; both pointers move on
        inx   d
        dcr   c             ; one fewer byte to go
        jnz   copy          ; repeat until the counter is 0
        hlt

source: db    10, 20, 30, 40, 50
dest:   ds    5

; Open the Memory panel: "dest" starts as zeros and fills with 10 20 30 40 50.
