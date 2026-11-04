; @title: Experiment 1 - Read switches and control LEDs
; @topic: IN, OUT and the accumulator (Virtual 8085 Trainer Kit)
; @validation: T
; @display: raw
;
; Virtual hardware (Lab > Show the Virtual 8085 Trainer Kit; see docs/TRAINER_KIT.md):
;   IN  00H   8 switches SW7..SW0    bit n = SWn, up = 1
;   OUT 01H   8 LEDs     LED7..LED0  bit n = 1 lights LEDn
; These port numbers are virtual teaching assignments, not real kit addresses.
;
; 1. Set the switches.  2. Predict the LEDs.  3. Assemble (F7).
; 4. Step Into (F11): after IN, look at A.  5. Step again: after OUT, look at the LEDs.
; Lab > Experiment 1 walks you through it and compares your prediction with the CPU.

START: IN 00H
       OUT 01H
       HLT
