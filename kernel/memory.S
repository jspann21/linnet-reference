#include "linnet_target.h"
.syntax unified
.cpu arm7tdmi
.arm
/* Compiler-required ARM EABI operations; no allocator or libc runtime. */
.section .text.ln_memory_copy,"ax",%progbits
.global ln_memory_copy
.global __aeabi_memcpy4
.global __aeabi_memcpy8
.global __aeabi_memcpy
.type ln_memory_copy,%function
ln_memory_copy:
__aeabi_memcpy4:
__aeabi_memcpy8:
__aeabi_memcpy:
    cmp r2, #0
    bxeq lr
    stmdb sp!, {r4-r10, lr}
    /* Align the destination first. Source and destination often differ in
     * alignment for LZ4 matches, so assemble those words from aligned loads
     * instead of falling back to a byte-at-a-time copy. */
.Lcopy_align:
    tst r0, #3
    beq .Lcopy_words
    ldrb r3, [r1], #1
    strb r3, [r0], #1
    subs r2, r2, #1
    beq .Lcopy_done
    b .Lcopy_align
.Lcopy_words:
    ands r12, r1, #3
    bne .Lcopy_shifted
    cmp r2, #32
    blo .Lcopy_word_tail
.Lcopy_blocks:
    ldmia r1!, {r3-r10}
    stmia r0!, {r3-r10}
    sub r2, r2, #32
    cmp r2, #32
    bhs .Lcopy_blocks
.Lcopy_word_tail:
    cmp r2, #4
    blo .Lcopy_tail
    ldr r3, [r1], #4
    str r3, [r0], #4
    sub r2, r2, #4
    b .Lcopy_word_tail
.Lcopy_tail:
    cmp r2, #0
    beq .Lcopy_done
.Lcopy_bytes:
    ldrb r3, [r1], #1
    strb r3, [r0], #1
    subs r2, r2, #1
    bne .Lcopy_bytes
    b .Lcopy_done
.Lcopy_shifted:
    /* Select immediate shifts once. Keep enough requested bytes for the
     * next aligned load, then reconstruct the logical pointer for the tail. */
    cmp r2, #8
    blo .Lcopy_tail
    mov lr, r12
    bic r1, r1, #3
    ldr r3, [r1], #4
    cmp r12, #1
    beq .Lcopy_shift_1
    cmp r12, #2
    beq .Lcopy_shift_2
    b .Lcopy_shift_3

.macro copy_shift alignment, right, left
.Lcopy_shift_\alignment:
    cmp r2, #20
    blo .Lcopy_shift_word_\alignment
.Lcopy_shift_block_\alignment:
    ldmia r1!, {r4-r7}
    mov r8, r3, lsr #\right
    orr r8, r8, r4, lsl #\left
    mov r9, r4, lsr #\right
    orr r9, r9, r5, lsl #\left
    mov r10, r5, lsr #\right
    orr r10, r10, r6, lsl #\left
    mov r12, r6, lsr #\right
    orr r12, r12, r7, lsl #\left
    stmia r0!, {r8-r10, r12}
    mov r3, r7
    sub r2, r2, #16
    cmp r2, #20
    bhs .Lcopy_shift_block_\alignment
.Lcopy_shift_word_\alignment:
    cmp r2, #8
    blo .Lcopy_shift_tail
    ldr r4, [r1], #4
    mov r5, r3, lsr #\right
    orr r5, r5, r4, lsl #\left
    str r5, [r0], #4
    mov r3, r4
    sub r2, r2, #4
    b .Lcopy_shift_word_\alignment
.endm

    copy_shift 1, 8, 24
    copy_shift 2, 16, 16
    copy_shift 3, 24, 8
.Lcopy_shift_tail:
    sub r1, r1, #4
    add r1, r1, lr
    b .Lcopy_tail
.Lcopy_done:
    ldmia sp!, {r4-r10, pc}
.size ln_memory_copy, .-ln_memory_copy
.section .text.ln_memory_clear,"ax",%progbits
.global ln_memory_clear
.global __aeabi_memclr4
.global __aeabi_memclr8
.global __aeabi_memclr
.type ln_memory_clear,%function
ln_memory_clear:
__aeabi_memclr4:
__aeabi_memclr8:
__aeabi_memclr:
    mov r2, #0
    cmp r1, #0
    bxeq lr
.Lclear_align:
    tst r0, #3
    beq .Lclear_words
    strb r2, [r0], #1
    subs r1, r1, #1
    bxeq lr
    b .Lclear_align
.Lclear_words:
    cmp r1, #32
    blo .Lclear_word_tail
    /* Large runtime resets (video, photos and library state) are common and
     * run after cache is enabled. Fill a 32-byte block per iteration;
     * preserve the callee-saved zero registers for the short tail below. */
    stmdb sp!, {r4-r8, lr}
    mov r3, #0
    mov r4, #0
    mov r5, #0
    mov r6, #0
    mov r7, #0
    mov r8, #0
    mov r12, #0
.Lclear_blocks:
    stmia r0!, {r2-r8, r12}
    sub r1, r1, #32
    cmp r1, #32
    bhs .Lclear_blocks
    ldmia sp!, {r4-r8, lr}
.Lclear_word_tail:
    cmp r1, #4
    blo .Lclear_tail
.Lclear_word:
    str r2, [r0], #4
    sub r1, r1, #4
    cmp r1, #4
    bhs .Lclear_word
.Lclear_tail:
    cmp r1, #0
    bxeq lr
.Lclear_bytes:
    strb r2, [r0], #1
    subs r1, r1, #1
    bne .Lclear_bytes
    bx lr
.size ln_memory_clear, .-ln_memory_clear

/* RGB565 2x2 transpose into the target panel's column order.
 * r0: destination at the first logical x/y; columns descend by one panel height.
 * r1: row-major source with panel-width pitch; r2/r3: positive even width/height.
 * Both pointers are word aligned. Each source pair becomes two column pairs. */
.section .text.ln_memory_columns,"ax",%progbits
.global ln_memory_columns
.type ln_memory_columns,%function
ln_memory_columns:
    push {r4-r11,lr}
    mov r8, #(LINNET_LCD_HEIGHT_ASM * 2)
    mul r4, r2, r8
    mov r8, r4
    mov r9, #(LINNET_LCD_WIDTH_ASM * 4)
    sub r9, r9, r2, lsl #1
    mov r10, r2, lsr #1
    mov r11, r3, lsr #1
.Lcolumns_rows:
    mov r12, r10
.Lcolumns_pair:
    ldr r4, [r1]
    ldr r5, [r1, #(LINNET_LCD_WIDTH_ASM * 2)]
    mov r6, r4, lsl #16
    mov r6, r6, lsr #16
    orr r6, r6, r5, lsl #16
    mov r7, r5, lsr #16
    mov r7, r7, lsl #16
    orr r7, r7, r4, lsr #16
    str r6, [r0]
    str r7, [r0, #-(LINNET_LCD_HEIGHT_ASM * 2)]
    add r1, r1, #4
    sub r0, r0, #(LINNET_LCD_HEIGHT_ASM * 4)
    subs r12, r12, #1
    bne .Lcolumns_pair
    add r0, r0, r8
    add r0, r0, #4
    add r1, r1, r9
    subs r11, r11, #1
    bne .Lcolumns_rows
    pop {r4-r11,pc}
.size ln_memory_columns, .-ln_memory_columns
