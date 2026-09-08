.syntax unified
.cpu arm7tdmi
.arm
#include "hal/pp5020/recovery.h"
#if defined(LINNET_PLATFORM_CORE)
#include "hal/pp5020/display.h"
#endif
.section .text.startup,"ax",%progbits
.global ln_platform_reset
ln_platform_reset:
    msr cpsr_c, #0xd3
    ldr r0, =0x6000c000
    ldr r1, [r0]
    tst r1, #1
    beq 2f
    ldr r2, =0xf000f044
    ldr r1, [r2]
    orr r1, r1, #6
    str r1, [r2]
    mov r3, #0x100000
1:  ldr r1, [r0]
    tst r1, #0x8000
    beq 2f
    subs r3, r3, #1
    bne 1b
    b ln_early_stop
2:  mov r1, #0
    str r1, [r0]
    nop
    nop
    nop
    ldr r0, =0x60000000
    ldrb r1, [r0]
    cmp r1, #0x55
    bne ln_cop_install
#if defined(LINNET_IMAGE_OS) && !defined(LINNET_PROFILE_RELEASE)
    ldr r0, =0x11ffe000
    mov r1, #0x40
    str r1, [r0, #128]
    LN_STARTUP_STAMP 3, 8
#endif
#if defined(LINNET_IMAGE_BOOT) && !defined(LINNET_PROFILE_RELEASE)
    /* Only a fresh CPU bootstrap through the native SDRAM alias may replace
     * the resident anchor. A low-address RAM Boot candidate preserves it.
     * Use the actual PC-relative entry minus its linked address, not a high
     * bit test that could accept a different relocation window. COP owns its
     * cookie/tick fields concurrently, so leave both untouched. */
    adr r0, ln_platform_reset
    ldr r1, =ln_platform_reset
    sub r0, r0, r1
    cmp r0, #0x10000000
    bne ln_keep_anchor
    ldr r0, =0x11ffe000
    mov r1, #0
    str r1, [r0, #20]
    str r1, [r0]
    str r1, [r0, #LN_STARTUP_TIMING_BASE]
ln_keep_anchor:
#endif
#if defined(LINNET_PROFILE_RELEASE) && !defined(LINNET_PLATFORM_CORE)
    ldr r0, =0x60007004
    mov r1, #0x80000000
    str r1, [r0]
    nop
    nop
    nop
    b ln_cpu_remap
#else
    /* Require a sleeping inherited COP or a live Linnet monitor handshake. */
    ldr r0, =0x60007004
    ldr r1, [r0]
    tst r1, #0x80000000
    bne ln_cpu_remap
    ldr r0, =0x11ffe000
    ldr r2, =0x4c4e434f
    ldr r4, [r0, #28]
    mov r3, #0x100000
10: ldr r1, [r0, #24]
    cmp r1, r2
    ldreq r1, [r0, #28]
    cmpeq r1, r4
    bne 11f
    subs r3, r3, #1
    bne 10b
    b ln_early_stop
11: ldr r1, [r0, #24]
    cmp r1, r2
    beq ln_cpu_remap
    subs r3, r3, #1
    bne 10b
    b ln_early_stop
#endif
ln_cpu_remap:
    adr r0, ln_remap_begin
    adr r1, ln_remap_end
    ldr r2, =0x40000000
3:  cmp r0, r1
    ldrlo r3, [r0], #4
    strlo r3, [r2], #4
    blo 3b
    ldr pc, =0x40000000
.align 2
ln_remap_begin:
    ldr r0, 4f
    ldr r1, 5f
    str r1, [r0]
    ldr r1, 6f
    str r1, [r0, #4]
    ldr pc, 7f
4:  .word 0xf000f000
5:  .word 0x00003e00
6:  .word 0x10000f84
7:  .word ln_reset_continue
ln_remap_end:
    .ltorg

/* Only COP entering Linnet is adopted; never wake an inherited parked COP. */
ln_cop_install:
#if defined(LINNET_PROFILE_RELEASE) && !defined(LINNET_PLATFORM_CORE)
    ldr r0, =0x60007004
    mov r1, #0x80000000
20: str r1, [r0]
    b 20b
#else
    adr r0, ln_cop_begin
#if defined(LINNET_PLATFORM_CORE)
    ldr r1, =ln_cop_end-ln_cop_begin
    add r1, r0, r1
#else
    adr r1, ln_cop_end
#endif
    ldr r2, =0x40001000
8:  cmp r0, r1
    ldrlo r3, [r0], #4
    strlo r3, [r2], #4
    blo 8b
    ldr pc, =0x40001000
.align 2
ln_cop_begin:
#if defined(LINNET_PLATFORM_CORE)
    ldr sp, ln_cop_stack_address
    ldr r0, ln_cop_mailbox_address
    mov r1, #0
    str r1, [r0, #LN_DISPLAY_ENABLED]
    str r1, [r0, #LN_DISPLAY_MAGIC]
    str r1, [r0, #LN_DISPLAY_PAUSE]
    str r1, [r0, #LN_DISPLAY_PAUSED]
#endif
    ldr r0, 13f
    mov r1, #0
    str r1, [r0, #20]
    ldr r1, 14f
    str r1, [r0, #24]
#if defined(LINNET_PLATFORM_CORE)
    ldr r1, ln_cop_capability_value
    str r1, [r0, #160]
#endif
    ldr r2, 15f
9:
#if defined(LINNET_PLATFORM_CORE)
    bl ln_cop_display_step
#endif
    ldr r3, [r2]
    str r3, [r0, #28]
    ldr r4, [r0, #20]
    cmp r4, #1
    bne 9b
    ldr r4, [r0, #16]
    sub r4, r3, r4
    ldr r5, 16f
    cmp r4, r5
    /* CPU may publish progress after our timer sample. A negative elapsed
     * value is a fresh lease, not an unsigned wrap past the reset deadline. */
    blt 9b
    ldr r5, 17f
    mov r6, #2
    str r6, [r5]
    ldr r5, 18f
    cmp r4, r5
    blo 9b
    ldr r5, 19f
    ldr r7, [r0, #152]
    cmp r7, #0
    moveq r7, #0xc0
    streq r7, [r0, #152]
    ldr r6, [r5]
    orr r6, r6, #4
    str r6, [r5]
12: b 12b
13: .word 0x11ffe000
14: .word 0x4c4e434f
15: .word 0x60005010
16: .word 750000
17: .word 0x60004018
18: .word 1500000
19: .word 0x60006004
#if defined(LINNET_PLATFORM_CORE)
ln_cop_stack_address: .word 0x40003000
ln_cop_mailbox_address: .word LINNET_DISPLAY_MAILBOX
ln_cop_capability_value: .word LINNET_DISPLAY_CAPABILITY

/* The complete worker remains in IRAM beside the watchdog monitor. There
 * are no branches or calls into the replaceable low SDRAM image. Each call
 * performs at most one command or32 pixel pairs before returning to watchdog. */
ln_cop_display_step:
    stmdb sp!, {r0-r7,lr}
    ldr r0, ln_cop_mailbox_address
    ldr r1, [r0, #LN_DISPLAY_PROBE]
    str r1, [r0, #LN_DISPLAY_PROBE_ACK]
    ldr r1, [r0, #LN_DISPLAY_PAUSE]
    cmp r1, #2
    beq ln_cop_display_clock_park
    cmp r1, #0
    movne r1, #1
    str r1, [r0, #LN_DISPLAY_PAUSED]
    bne ln_cop_display_done
ln_cop_display_work:
    ldr r1, [r0, #LN_DISPLAY_ENABLED]
    cmp r1, #1
    bne ln_cop_display_done
    ldr r1, [r0, #LN_DISPLAY_MAGIC]
    ldr r2, ln_cop_display_magic
    cmp r1, r2
    bne ln_cop_display_done
    ldr r1, [r0, #LN_DISPLAY_TICKS]
    add r1, r1, #1
    str r1, [r0, #LN_DISPLAY_TICKS]
    ldr r1, [r0, #LN_DISPLAY_STATE]
    cmp r1, #0
    beq ln_cop_display_begin
    ldr r2, ln_cop_timer_address
    ldr r2, [r2]
    ldr r3, [r0, #LN_DISPLAY_STARTED]
    sub r2, r2, r3
    ldr r3, ln_cop_display_deadline
    cmp r2, r3
    movhs r1, #1
    bhs ln_cop_display_fail
    ldr r2, [r0, #LN_DISPLAY_BUDGET]
    cmp r2, #0
    moveq r1, #2
    beq ln_cop_display_fail
    sub r2, r2, #1
    str r2, [r0, #LN_DISPLAY_BUDGET]
    cmp r1, #1
    beq ln_cop_display_command
    cmp r1, #2
    beq ln_cop_display_block
    cmp r1, #3
    beq ln_cop_display_pair
    cmp r1, #4
    beq ln_cop_display_ready
    mov r1, #5
    b ln_cop_display_fail
ln_cop_display_clock_park:
    ldr r1, [r0, #LN_DISPLAY_STATE]
    cmp r1, #0
    bne ln_cop_display_work
    /* Acknowledge only between LCD jobs, then self-park at a resident IRAM
     * instruction. CPU must observe COP_CTL sleep before changing clocks. */
    ldr r1, [r0, #LN_DISPLAY_PAUSE]
    cmp r1, #2
    bne ln_cop_display_done
    mov r1, #2
    str r1, [r0, #LN_DISPLAY_PAUSED]
    ldr r2, ln_cop_control_address
    mov r1, #0x80000000
    str r1, [r2]
    nop
    nop
    nop
    mov r1, #0
    str r1, [r0, #LN_DISPLAY_PAUSED]
    b ln_cop_display_done
ln_cop_display_begin:
    ldr r1, [r0, #LN_DISPLAY_HEAD]
    ldr r2, [r0, #LN_DISPLAY_TAIL]
    subs r3, r1, r2
    beq ln_cop_display_done
    cmp r3, #8
    movhi r1, #3
    bhi ln_cop_display_fail
    and r2, r2, #7
    add r2, r0, r2, lsl #4
    add r2, r2, #LN_DISPLAY_QUEUE
    ldmia r2, {r3-r6}
    cmp r3, #220
    bhs ln_cop_display_bad_rectangle
    cmp r4, #176
    bhs ln_cop_display_bad_rectangle
    cmp r5, #0
    beq ln_cop_display_bad_rectangle
    cmp r6, #0
    beq ln_cop_display_bad_rectangle
    rsb r7, r3, #220
    cmp r5, r7
    bhi ln_cop_display_bad_rectangle
    rsb r7, r4, #176
    cmp r6, r7
    bhi ln_cop_display_bad_rectangle
    orr r7, r3, r5
    tst r7, #1
    bne ln_cop_display_bad_rectangle
    ldr r7, [r0, #LN_DISPLAY_BUFFER]
    tst r7, #3
    bne ln_cop_display_bad_rectangle
    cmp r7, #0x10000000
    blo ln_cop_display_bad_rectangle
    ldr r1, ln_cop_buffer_limit
    cmp r7, r1
    bhi ln_cop_display_bad_rectangle
    str r3, [r0, #LN_DISPLAY_X]
    str r4, [r0, #LN_DISPLAY_Y]
    str r5, [r0, #LN_DISPLAY_WIDTH]
    str r6, [r0, #LN_DISPLAY_HEIGHT]
    str r6, [r0, #LN_DISPLAY_ROWS_LEFT]
    mov r1, #0
    str r1, [r0, #LN_DISPLAY_COMMAND]
    str r1, [r0, #LN_DISPLAY_X_CURSOR]
    str r1, [r0, #LN_DISPLAY_Y_CURSOR]
    ldr r1, ln_cop_display_budget
    str r1, [r0, #LN_DISPLAY_BUDGET]
    ldr r1, ln_cop_timer_address
    ldr r1, [r1]
    str r1, [r0, #LN_DISPLAY_STARTED]
    mov r1, #1
    str r1, [r0, #LN_DISPLAY_STATE]
    b ln_cop_display_done
ln_cop_display_bad_rectangle:
    mov r1, #4
    b ln_cop_display_fail
ln_cop_display_command:
    ldr r2, ln_cop_lcd_port
    ldr r3, [r2]
    tst r3, #0x80000000
    bne ln_cop_display_done
    ldr r1, [r0, #LN_DISPLAY_COMMAND]
    cmp r1, #0
    moveq r3, #0x12
    beq ln_cop_display_send_command
    cmp r1, #1
    ldreq r3, [r0, #LN_DISPLAY_Y]
    beq ln_cop_display_send_command
    cmp r1, #2
    moveq r3, #0x13
    beq ln_cop_display_send_command
    cmp r1, #3
    ldreq r3, [r0, #LN_DISPLAY_X]
    rsbeq r3, r3, #219
    beq ln_cop_display_send_command
    cmp r1, #4
    moveq r3, #0x15
    beq ln_cop_display_send_command
    cmp r1, #5
    ldreq r3, [r0, #LN_DISPLAY_Y]
    ldreq r4, [r0, #LN_DISPLAY_HEIGHT]
    addeq r3, r3, r4
    subeq r3, r3, #1
    beq ln_cop_display_send_command
    cmp r1, #6
    moveq r3, #0x16
    beq ln_cop_display_send_command
    ldr r3, [r0, #LN_DISPLAY_X]
    ldr r4, [r0, #LN_DISPLAY_WIDTH]
    add r3, r3, r4
    rsb r3, r3, #220
ln_cop_display_send_command:
    orr r3, r3, #0x80000000
    str r3, [r2]
    add r1, r1, #1
    str r1, [r0, #LN_DISPLAY_COMMAND]
    cmp r1, #8
    moveq r1, #2
    streq r1, [r0, #LN_DISPLAY_STATE]
    b ln_cop_display_done
ln_cop_display_block:
    ldr r2, ln_cop_lcd_port
    ldr r3, [r2]
    tst r3, #0x80000000
    bne ln_cop_display_done
    ldr r2, [r0, #LN_DISPLAY_ROWS_LEFT]
    cmp r2, #128
    movhi r2, #128
    str r2, [r0, #LN_DISPLAY_BLOCK_ROWS]
    ldr r3, [r0, #LN_DISPLAY_WIDTH]
    mul r4, r2, r3
    mov r3, r4, lsr #1
    str r3, [r0, #LN_DISPLAY_PAIRS_LEFT]
    mov r4, r4, lsl #1
    sub r4, r4, #1
    ldr r2, ln_cop_lcd_control
    ldr r3, ln_cop_lcd_start
    str r3, [r2]
    ldr r3, ln_cop_lcd_configuration
    orr r4, r4, r3
    str r4, [r2, #4]
    mov r3, #0x34000000
    str r3, [r2]
    mov r1, #3
    str r1, [r0, #LN_DISPLAY_STATE]
    b ln_cop_display_done
/* The entry/monitor prefix is unchanged, including its signed lease guard.
 * The worker already charged one work-budget unit before this dispatch.
 * Transfer at most32 ready FIFO words within one row, then return to the
 * watchdog. Register ownership is the existing saved {r0-r7,lr} frame. */
ln_cop_display_pair:
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
    beq ln_cop_display_burst_done
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
    ldr r2, ln_cop_lcd_control
    ldr r3, ln_cop_lcd_data
    ldr r4, ln_cop_byte_mask
    mov lr, #0
ln_cop_display_burst_pair:
    ldr r6, [r2]
    tst r6, #0x01000000
    beq ln_cop_display_burst_commit
    ldr r6, [r1], #4
    mov r7, r6, lsr #8
    and r7, r7, r4
    and r6, r6, r4
    orr r6, r7, r6, lsl #8
    str r6, [r3]
    add lr, lr, #1
    subs r5, r5, #1
    bne ln_cop_display_burst_pair
ln_cop_display_burst_commit:
    cmp lr, #0
    beq ln_cop_display_burst_done
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
ln_cop_display_burst_done:
    b ln_cop_display_done
ln_cop_display_ready:
    ldr r2, ln_cop_lcd_control
    ldr r3, [r2]
    tst r3, #0x04000000
    beq ln_cop_display_done
    mov r3, #0
    str r3, [r2, #4]
    ldr r2, [r0, #LN_DISPLAY_ROWS_LEFT]
    ldr r3, [r0, #LN_DISPLAY_BLOCK_ROWS]
    subs r2, r2, r3
    str r2, [r0, #LN_DISPLAY_ROWS_LEFT]
    movne r1, #2
    strne r1, [r0, #LN_DISPLAY_STATE]
    bne ln_cop_display_done
    mov r1, #0
    str r1, [r0, #LN_DISPLAY_STATE]
    ldr r1, [r0, #LN_DISPLAY_TAIL]
    add r1, r1, #1
    str r1, [r0, #LN_DISPLAY_TAIL]
    ldr r1, [r0, #LN_DISPLAY_COMPLETED]
    add r1, r1, #1
    str r1, [r0, #LN_DISPLAY_COMPLETED]
    b ln_cop_display_done
ln_cop_display_fail:
    str r1, [r0, #LN_DISPLAY_ERROR]
    ldr r1, [r0, #LN_DISPLAY_FAILURES]
    add r1, r1, #1
    str r1, [r0, #LN_DISPLAY_FAILURES]
    ldr r1, ln_cop_lcd_control
    mov r2, #0
    str r2, [r1, #4]
    str r2, [r0, #LN_DISPLAY_STATE]
    ldr r1, [r0, #LN_DISPLAY_HEAD]
    str r1, [r0, #LN_DISPLAY_TAIL]
ln_cop_display_done:
    ldmia sp!, {r0-r7,pc}
ln_cop_display_magic: .word LINNET_DISPLAY_MAGIC
ln_cop_timer_address: .word 0x60005010
ln_cop_display_deadline: .word 500000
ln_cop_display_budget: .word 1000000
ln_cop_buffer_limit: .word 0x10800000-LINNET_DISPLAY_BYTES
ln_cop_lcd_port: .word 0x70008a0c
ln_cop_lcd_control: .word 0x70008a20
ln_cop_lcd_data: .word 0x70008b00
ln_cop_lcd_start: .word 0x10000080
ln_cop_lcd_configuration: .word 0xc0010000
ln_cop_byte_mask: .word 0x00ff00ff
ln_cop_control_address: .word 0x60007004
#endif
ln_cop_end:
    .ltorg
#endif
