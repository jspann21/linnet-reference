.syntax unified
.cpu arm7tdmi
.arm
#include "hal/pp5020/display.h"
.section .text.ln_video_blit_blob,"ax",%progbits
.balign 4
.global ln_video_blit_begin
.global ln_video_blit_end
/* Entered by the verified old worker's state-3 BEQ. That worker has already
 * saved {r0-r7,lr}, checked deadline, and charged one work-budget unit.
 * Never call SDRAM code or use registers r8-r12. Return through its saved PC.
 * Each invocation writes <=32 pairs and never crosses a scanline boundary. */
ln_video_blit_begin:
    ldr r5, [r0, #LN_DISPLAY_WIDTH]
    ldr r6, [r0, #LN_DISPLAY_X_CURSOR]
    sub r5, r5, r6
    mov r5, r5, lsr #1
    cmp r5, #32
    movhi r5, #32
    ldr r7, [r0, #LN_DISPLAY_PAIRS_LEFT]
    cmp r5, r7
    movhi r5, r7
    ldr r7, [r0, #LN_DISPLAY_BUDGET]
    add r7, r7, #1
    cmp r5, r7
    movhi r5, r7
    cmp r5, #0
    beq .Lreturn
    ldr r1, [r0, #LN_DISPLAY_Y]
    ldr r7, [r0, #LN_DISPLAY_Y_CURSOR]
    add r1, r1, r7
    mov r7, #220
    mul r2, r1, r7
    ldr r7, [r0, #LN_DISPLAY_X]
    add r2, r2, r7
    add r2, r2, r6
    ldr r1, [r0, #LN_DISPLAY_BUFFER]
    add r1, r1, r2, lsl #1
    ldr r2, .Lcontrol
    ldr r3, .Ldata
    ldr r4, .Lmask
    mov lr, #0
.Lpair:
    /* Brief FIFO backpressure is cheaper to retry here than to re-enter
     * the monitor and rebuild the source address. Bound each retry so a
     * stalled LCD still returns to the lease/deadline checks. */
    mov r7, #32
.Lpair_wait:
    ldr r6, [r2]
    tst r6, #0x01000000
    bne .Lpair_ready
    subs r7, r7, #1
    bne .Lpair_wait
    b .Lcommit
.Lpair_ready:
    ldr r6, [r1], #4
    mov r7, r6, lsr #8
    and r7, r7, r4
    and r6, r6, r4
    orr r6, r7, r6, lsl #8
    str r6, [r3]
    add lr, lr, #1
    subs r5, r5, #1
    bne .Lpair
.Lcommit:
    cmp lr, #0
    beq .Lreturn
    ldr r1, [r0, #LN_DISPLAY_X_CURSOR]
    add r1, r1, lr, lsl #1
    ldr r2, [r0, #LN_DISPLAY_WIDTH]
    cmp r1, r2
    moveq r1, #0
    ldreq r2, [r0, #LN_DISPLAY_Y_CURSOR]
    addeq r2, r2, #1
    streq r2, [r0, #LN_DISPLAY_Y_CURSOR]
    str r1, [r0, #LN_DISPLAY_X_CURSOR]
    ldr r1, [r0, #LN_DISPLAY_PAIRS]
    add r1, r1, lr
    str r1, [r0, #LN_DISPLAY_PAIRS]
    ldr r1, [r0, #LN_DISPLAY_BUDGET]
    add r1, r1, #1
    sub r1, r1, lr
    str r1, [r0, #LN_DISPLAY_BUDGET]
    ldr r1, [r0, #LN_DISPLAY_PAIRS_LEFT]
    subs r1, r1, lr
    str r1, [r0, #LN_DISPLAY_PAIRS_LEFT]
    moveq r1, #4
    streq r1, [r0, #LN_DISPLAY_STATE]
.Lreturn:
    ldmia sp!, {r0-r7,pc}
.Lcontrol: .word 0x70008a20
.Ldata: .word 0x70008b00
.Lmask: .word 0x00ff00ff
ln_video_blit_end:
