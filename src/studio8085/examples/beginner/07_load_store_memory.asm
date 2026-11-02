; @title: Reading and writing memory
; @topic: LDA, STA, DB and DS
; @validation: T
;
; Memory is a long row of numbered bytes. A label is a name for a memory address.
;   LDA addr   copy the byte at addr INTO register A
;   STA addr   copy register A INTO the byte at addr
;   DB         define a byte with a starting value
;   DS         reserve bytes that start at 0
;
; Open the Memory panel and look for the numbers 30 (1Eh) and 12 (0Ch).

        lda   first         ; A = 30
        mov   b,a           ; keep it in B
        lda   second        ; A = 12
        add   b             ; A = 12 + 30 = 42
        sta   total         ; write the answer into memory
        hlt

first:  db    30            ; a byte that starts as 30
second: db    12            ; a byte that starts as 12
total:  ds    1             ; room for the answer

; Try it: change 30 and 12 to other numbers. The program code is unchanged!
