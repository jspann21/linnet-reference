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
    /* ARM7 cannot load unaligned words. Match alignment before widening;
     * mismatched addresses retain the byte path. Only caller-saved registers
     * are touched, including by the generic EABI aliases. */
    eor r3, r0, r1
    tst r3, #3
    bne .Lcopy_bytes
.Lcopy_align:
    tst r0, #3
    beq .Lcopy_words
    ldrb r3, [r1], #1
    strb r3, [r0], #1
    subs r2, r2, #1
    bxeq lr
    b .Lcopy_align
.Lcopy_words:
    cmp r2, #8
    blo .Lcopy_word_tail
.Lcopy_pairs:
    ldmia r1!, {r3, r12}
    stmia r0!, {r3, r12}
    sub r2, r2, #8
    cmp r2, #8
    bhs .Lcopy_pairs
.Lcopy_word_tail:
    cmp r2, #4
    blo .Lcopy_tail
    ldr r3, [r1], #4
    str r3, [r0], #4
    sub r2, r2, #4
.Lcopy_tail:
    cmp r2, #0
    bxeq lr
.Lcopy_bytes:
    ldrb r3, [r1], #1
    strb r3, [r0], #1
    subs r2, r2, #1
    bne .Lcopy_bytes
    bx lr
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
    cmp r1, #12
    blo .Lclear_word_tail
    mov r3, #0
    mov r12, #0
.Lclear_triples:
    stmia r0!, {r2, r3, r12}
    sub r1, r1, #12
    cmp r1, #12
    bhs .Lclear_triples
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
