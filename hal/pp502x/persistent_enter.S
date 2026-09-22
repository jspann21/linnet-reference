.syntax unified
.cpu arm7tdmi
.arm
.section .text.persistent_enter,"ax",%progbits
.align 2
.global ln_persistent_enter_begin
.global ln_persistent_enter_end
/* IRAM-resident copy after verified persistent selection; no development API. */
ln_persistent_enter_begin:
    msr cpsr_c, #0xd3
1:  cmp r1, #4
    ldrhs r4, [r0], #4
    strhs r4, [r2], #4
    subhs r1, r1, #4
    bhs 1b
2:  cmp r1, #0
    ldrbne r4, [r0], #1
    strbne r4, [r2], #1
    subne r1, r1, #1
    bne 2b
    bx r3
ln_persistent_enter_end:
