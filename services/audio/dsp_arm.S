/* SPDX-License-Identifier: GPL-2.0-or-later
 * Accumulator ordering/register allocation adapted from Rockbox filter_process:
 * https://github.com/Rockbox/rockbox, lib/rbcodec/dsp/dsp_arm.S
 * 99c18f336c730f533d3b7d2d8951f5dc4a6da802, CRLF source SHA-256
 * 4cd808d3e03981c5a4112fb7248626e5064dc7c8f7620b0d24cc003b3f76600b.
 * Copyright (C) 2006-2007 Thom Johansen
 * Copyright (C) 2010 Bertrik Sikken
 * Copyright (C) 2012 Michael Sevakis
 * This program is free software under the GNU General Public License,
 * version 2 or (at your option) any later version; provided AS IS without
 * warranty. The full license is in third_party/libmad/COPYING.
 * Linnet adaptation: calling interface, fixed Q8/Q2.30 scaling, bounded stride loops,
 * rounding, guarding and clip counting below.
 *
 * Exact portable DSP semantics: symmetric nearest/ties-away rounding, +/-2^27
 * guard, saturating clip count. No ARMv5+ instructions or unaligned accesses.
 * r0=coefficients, r1=history, r2=samples, r3=count; stack=stride,clips pointer.
 * Only internal callers with stride 1 or 2 and validated coefficients use this.
 */
.syntax unified
.cpu arm7tdmi
.arm
.text
.align 2
.global ln_dsp_filter_arm
.type ln_dsp_filter_arm,%function
ln_dsp_filter_arm:
    push {r4-r11,lr}
    sub sp,sp,#20
    str r1,[sp]
    ldr lr,[sp,#60]
    str lr,[sp,#4]
    mov lr,r3
    mov r3,r2
    mov r2,lr
    cmp r2,#0
    beq .Lreturn
    ldm r0,{r4-r8}
    /* Jury validation excludes INT_MIN a1; |a2| < 2^30. */
    rsb r7,r7,#0
    rsb r8,r8,#0
    ldm r1,{r9-r12}
    ldr lr,[sp,#56]
    cmp lr,#1
    beq .Lmono
    b .Lstereo

.macro FILTER_LOOP name,step
\name:
    smull r0,r1,r5,r9
    smlal r0,r1,r6,r10
    mov r10,r9
    ldr r9,[r3]
    smlal r0,r1,r7,r11
    smlal r0,r1,r8,r12
    smlal r0,r1,r4,r9
    /* floor((sum + 2^29 - (sum < 0)) / 2^30) rounds ties away.
     * Carry-propagating addition preserves every low accumulator bit. */
    mov lr,r1,asr #31
    adds r0,r0,#0x20000000
    adc r1,r1,#0
    adds r0,r0,lr
    adc r1,r1,lr
    mov r12,r11
    mov r11,r0,lsr #30
    orr r11,r11,r1,lsl #2
    cmp r11,#0x08000000
    movgt r11,#0x08000000
    bgt .Lclip\@
    cmn r11,#0x08000000
    movlt r11,#0xf8000000
    blt .Lclip\@
.Lstore\@:
    str r11,[r3],#\step
    subs r2,r2,#1
    bne \name
    b .Ldone
.Lclip\@:
    ldr r0,[sp,#4]
    ldr r1,[r0]
    adds r1,r1,#1
    mvncs r1,#0
    str r1,[r0]
    b .Lstore\@
.endm

FILTER_LOOP .Lmono,4
FILTER_LOOP .Lstereo,8
.Ldone:
    ldr r0,[sp]
    stm r0,{r9-r12}
.Lreturn:
    add sp,sp,#20
    pop {r4-r11,lr}
    bx lr
.size ln_dsp_filter_arm,.-ln_dsp_filter_arm


/* Round a signed 64-bit accumulator by 16 with symmetric ties away. */
.macro ROUND16 destination,lo,hi,scratch
    mov \scratch,\hi,lsr #31
    rsb \scratch,\scratch,#0x8000
    adds \lo,\lo,\scratch
    adc \hi,\hi,#0
    mov \destination,\lo,lsr #16
    orr \destination,\destination,\hi,lsl #16
.endm

/* r0=interleaved Q8 samples, r1=frames, r2=two histories, r3=coefficient;
 * stack=amount. Guarded samples and convex histories keep differences within
 * +/-2^28. Histories and configuration stay in registers for the whole block.
 * Mix identity x*(65536-a)+low*a = x*65536+(low-x)*a saves one multiply,
 * with the complete signed64 sum retained before rounding (including ties). */
.align 2
.global ln_dsp_crossfeed_stereo_arm
.type ln_dsp_crossfeed_stereo_arm,%function
ln_dsp_crossfeed_stereo_arm:
    push {r4-r11,lr}
    ldr r7,[sp,#36]
    push {r2}
    mov r6,r3
    ldm r2,{r4,r5}
    cmp r1,#0
    beq .Lcrossdone
.Lcrossloop:
    ldm r0,{r8,r9}
    sub r12,r8,r4
    smull r10,r11,r6,r12
    ROUND16 r12,r10,r11,r3
    add r4,r4,r12
    sub r12,r9,r5
    smull r10,r11,r6,r12
    ROUND16 r12,r10,r11,r3
    add r5,r5,r12
    sub r12,r5,r8
    smull r10,r11,r7,r12
    adds r10,r10,r8,lsl #16
    adc r11,r11,r8,asr #16
    ROUND16 r12,r10,r11,r3
    str r12,[r0],#4
    sub r12,r4,r9
    smull r10,r11,r7,r12
    adds r10,r10,r9,lsl #16
    adc r11,r11,r9,asr #16
    ROUND16 r12,r10,r11,r3
    str r12,[r0],#4
    subs r1,r1,#1
    bne .Lcrossloop
.Lcrossdone:
    pop {r2}
    stm r2,{r4,r5}
    pop {r4-r11,lr}
    bx lr
.size ln_dsp_crossfeed_stereo_arm,.-ln_dsp_crossfeed_stereo_arm

/* r0=Q8 samples, r1=count, r2=validated positive Q16 gain, r3=clip counter.
 * The largest rounded magnitude is 2^31, so inspect signed64 high bits before
 * narrowing. Clipping and the counter exactly match the portable guard. */
.align 2
.global ln_dsp_gain_arm
.type ln_dsp_gain_arm,%function
ln_dsp_gain_arm:
    push {r4-r7,lr}
    cmp r1,#0
    beq .Lgainreturn
    /* Attenuation of already guarded samples cannot clip. Choose once per
     * block, preserving the clip counter untouched on this common path. */
    cmp r2,#0x10000
    bls .Lgainattenuate
    ldr r7,[r3]
.Lgainloop:
    ldr r4,[r0]
    smull r5,r6,r2,r4
    /* Compare against Q8 guard in the original Q24 product. Rounding can
     * reach the guard from below without clipping, hence round first. */
    mov r4,r6,lsr #31
    rsb r4,r4,#0x8000
    adds r5,r5,r4
    adc r6,r6,#0
    cmp r6,#0x800
    bgt .Lgainpositive
    blt .Lgainnegativecheck
    /* Rounded value > GUARD iff high=0x800 and low >= 0x10000. */
    cmp r5,#0x10000
    bhs .Lgainpositive
.Lgainnarrow:
    mov r4,r5,lsr #16
    orr r4,r4,r6,lsl #16
.Lgainstore:
    str r4,[r0],#4
    subs r1,r1,#1
    bne .Lgainloop
.Lgaindone:
    str r7,[r3]
.Lgainreturn:
    pop {r4-r7,lr}
    bx lr
.Lgainattenuate:
    ldr r4,[r0]
    smull r5,r6,r2,r4
    ROUND16 r4,r5,r6,r7
    str r4,[r0],#4
    subs r1,r1,#1
    bne .Lgainattenuate
    b .Lgainreturn
.Lgainnegativecheck:
    cmn r6,#0x800
    bge .Lgainnarrow
    mov r4,#0xf8000000
    b .Lgainclip
.Lgainpositive:
    mov r4,#0x08000000
.Lgainclip:
    adds r7,r7,#1
    mvncs r7,#0
    b .Lgainstore
.size ln_dsp_gain_arm,.-ln_dsp_gain_arm
