.syntax unified
.cpu arm7tdmi
.arm
.section .text.ln_video_copy_rgb565,"ax",%progbits
.global ln_video_copy_rgb565
.type ln_video_copy_rgb565,%function
/* r0=destination, r1=source, r2=pixel count. Both buffers are halfword
 * aligned and disjoint. Convert big-endian RGB565 to native little-endian,
 * touching exactly count*2 bytes; zero and odd counts are supported. */
.macro swap_pair reg
    and r11, \reg, r12
    and \reg, r12, \reg, lsr #8
    orr \reg, \reg, r11, lsl #8
.endm
.macro half_pair
    ldrh r3, [r1], #2
    ldrh r4, [r1], #2
    orr r3, r3, r4, lsl #16
    swap_pair r3
    str r3, [r0], #4
.endm
ln_video_copy_rgb565:
    cmp r2, #0
    bxeq lr
    push {r4-r11, lr}
    tst r0, #2
    beq .Lpixel_aligned
    ldrh r3, [r1], #2
    mov r4, r3, lsr #8
    orr r3, r4, r3, lsl #8
    strh r3, [r0], #2
    subs r2, r2, #1
    beq .Lpixel_done
.Lpixel_aligned:
    mov r12, #255
    orr r12, r12, r12, lsl #16
    tst r1, #2
    bne .Lpixel_half_blocks
.Lpixel_word_blocks:
    cmp r2, #16
    blo .Lpixel_word_pairs
    ldmia r1!, {r3-r10}
    swap_pair r3
    swap_pair r4
    swap_pair r5
    swap_pair r6
    swap_pair r7
    swap_pair r8
    swap_pair r9
    swap_pair r10
    stmia r0!, {r3-r10}
    sub r2, r2, #16
    b .Lpixel_word_blocks
.Lpixel_word_pairs:
    cmp r2, #2
    blo .Lpixel_tail
    ldr r3, [r1], #4
    swap_pair r3
    str r3, [r0], #4
    sub r2, r2, #2
    b .Lpixel_word_pairs
.Lpixel_half_blocks:
    cmp r2, #8
    blo .Lpixel_half_pairs
    half_pair
    half_pair
    half_pair
    half_pair
    sub r2, r2, #8
    b .Lpixel_half_blocks
.Lpixel_half_pairs:
    cmp r2, #2
    blo .Lpixel_tail
    half_pair
    sub r2, r2, #2
    b .Lpixel_half_pairs
.Lpixel_tail:
    cmp r2, #0
    beq .Lpixel_done
    ldrh r3, [r1]
    mov r4, r3, lsr #8
    orr r3, r4, r3, lsl #8
    strh r3, [r0]
.Lpixel_done:
    pop {r4-r11, lr}
    bx lr
.size ln_video_copy_rgb565, .-ln_video_copy_rgb565
.section .note.GNU-stack,"",%progbits
