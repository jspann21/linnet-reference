#if defined(LINNET_IMAGE_BOOT) && defined(LINNET_PLATFORM_CORE) && defined(LINNET_STORAGE)
#define LINNET_BOOT_HASH_IRAM 1
#ifdef LINNET_AUDIO
#error Boot hash IRAM and audio IRAM cannot coexist
#endif
#endif
ENTRY(ln_start)
MEMORY {
  SDRAM (rwx) : ORIGIN = 0, LENGTH = 0x00800000
#if !defined(LINNET_PROFILE_RELEASE) || defined(LINNET_STORAGE)
  STAGE (rw) : ORIGIN = 0x01000000, LENGTH = 0x00800000
#endif
#ifndef LINNET_PROFILE_RELEASE
  SNAPSHOT (rw) : ORIGIN = 0x01e00000, LENGTH = 0x00100000
  CAPTURE (rw) : ORIGIN = 0x01f00000, LENGTH = 0x00013000
  USB_DMA (rw) : ORIGIN = 0x4000c000, LENGTH = 0xe00
#endif
#if !defined(LINNET_PROFILE_RELEASE) || defined(LINNET_PLATFORM_CORE)
  CONTROL (rw) : ORIGIN = 0x01ffe000, LENGTH = 0x1000
#endif
#ifdef LINNET_PLATFORM_CORE
  COP_MAILBOX (rw) : ORIGIN = 0x01ffd000, LENGTH = 0x1000
  COP_IRAM (rwx) : ORIGIN = 0x40001000, LENGTH = 0x2000
#ifdef LINNET_BOOT_HASH_IRAM
  BOOT_HASH_IRAM (rwx) : ORIGIN = 0x40003000, LENGTH = 0x1000
#endif
  CLOCK_IRAM (rwx) : ORIGIN = 0x4000d000, LENGTH = 0x200
#ifdef LINNET_AUDIO
  AUDIO_IRAM (rwx) : ORIGIN = 0x40003000, LENGTH = 0x2000
  CACHE_IRAM (rwx) : ORIGIN = 0x4000d200, LENGTH = 0xe00
#endif
  CACHE_STACK (rw) : ORIGIN = 0x4000e000, LENGTH = 0x1000
#endif
  MAILBOX (rw) : ORIGIN = 0x01fff000, LENGTH = 0x1000
}
SECTIONS {
  .vectors : { KEEP(*(.vectors)) } > SDRAM
  .text : { *(.text.startup) *(.text*) *(.rodata*) } > SDRAM
  .data : { *(.data*) . = ALIGN(4); } > SDRAM
#ifdef LINNET_BOOT_HASH_IRAM
  /* Separate Boot ownership, not an implicit reuse of the OS reservation. */
  .boot_hash ORIGIN(BOOT_HASH_IRAM) : ALIGN(4) {
    __boot_hash_begin = .;
    KEEP(*(.boot_hash.text)) KEEP(*(.boot_hash.rodata))
    . = ALIGN(4);
    __boot_hash_end = .;
  } > BOOT_HASH_IRAM AT> SDRAM
  __boot_hash_load = LOADADDR(.boot_hash);
  __image_end = LOADADDR(.boot_hash) + SIZEOF(.boot_hash);
  ASSERT(SIZEOF(.boot_hash) <= LENGTH(BOOT_HASH_IRAM), "Boot hash IRAM overflow")
  ASSERT(((ABSOLUTE(__boot_hash_begin) | ABSOLUTE(__boot_hash_end) | ABSOLUTE(__boot_hash_load)) & 3) == 0, "Boot hash copy alignment")
  ASSERT(ORIGIN(BOOT_HASH_IRAM) >= ORIGIN(COP_IRAM) + LENGTH(COP_IRAM), "Boot hash overlaps COP stack")
  ASSERT(ORIGIN(BOOT_HASH_IRAM) + LENGTH(BOOT_HASH_IRAM) <= 0x4000c000, "Boot hash overlaps USB DMA")
  .bss ALIGN(__image_end, 32) (NOLOAD)
#elif defined(LINNET_AUDIO)
  /* Keep the stored copy contiguous with the SDRAM image. The VMA is beyond
   * the COP's downward-growing stack, and below development USB DMA. */
  .audio_icode ORIGIN(AUDIO_IRAM) : ALIGN(4) {
    __audio_icode_begin = .;
    *(.audio_icode*)
    . = ALIGN(4);
    __audio_icode_end = .;
  } > AUDIO_IRAM AT> SDRAM
  __audio_icode_load = LOADADDR(.audio_icode);
  __image_end = LOADADDR(.audio_icode) + SIZEOF(.audio_icode);
  ASSERT(SIZEOF(.audio_icode) <= LENGTH(AUDIO_IRAM), "Audio IRAM code and veneers exceed 8 KiB")
  ASSERT(((ABSOLUTE(__audio_icode_begin) | ABSOLUTE(__audio_icode_end) | ABSOLUTE(__audio_icode_load)) & 3) == 0, "Audio IRAM copy must be word aligned")
  /* BSS must not overlap the stored copy used by startup and recovery. */
  .bss ALIGN(__image_end, 32) (NOLOAD)
#else
  __image_end = .;
  .bss (NOLOAD)
#endif
  : { . = ALIGN(8); __bss_start = .; *(.bss*) *(COMMON) . = ALIGN(8); __bss_end = .; } > SDRAM
  .stacks (NOLOAD) : {
    . = ALIGN(8); . += 1024; __abort_stack = .;
    . += 1024; __undef_stack = .;
    . += 1024; __irq_stack = .;
    . += 1024; __fiq_stack = .;
#if defined(LINNET_AUDIO)
    /* libmad Layer III plus decoder/foreground frames need more than8 KiB. */
    . += 32768; __stack_top = .;
#else
    . += 8192; __stack_top = .;
#endif
  } > SDRAM
  .noinit (NOLOAD) : { KEEP(*(.noinit*)) } > MAILBOX
#ifdef LINNET_STORAGE
  .persistent_handoff 0x01fff100 (NOLOAD) : { . += 0x80; } > MAILBOX
  ASSERT(SIZEOF(.noinit) <= 0x100, "Retained crash record overlaps persistent handoff")
#endif
#ifdef LINNET_PLATFORM_CORE
  .cop_mailbox (NOLOAD) : { . += 0x1000; } > COP_MAILBOX
  .cop_iram (NOLOAD) : { . += 0x2000; } > COP_IRAM
  .clock_iram (NOLOAD) : { . += 0x200; } > CLOCK_IRAM
#ifdef LINNET_AUDIO
  .cache_iram (NOLOAD) : { . += 0xe00; } > CACHE_IRAM
#endif
  .cache_stack (NOLOAD) : { . += 0x1000; } > CACHE_STACK
#endif
#if defined(LINNET_STORAGE) && defined(LINNET_PROFILE_RELEASE)
  .update_staging (NOLOAD) : { . += 0x00800000; } > STAGE
#endif
#ifndef LINNET_PROFILE_RELEASE
  .dev_staging (NOLOAD) : { . += 0x00800000; } > STAGE
  .dev_snapshot (NOLOAD) : { . += 0x00100000; } > SNAPSHOT
  .dev_capture (NOLOAD) : { *(.dev_capture) } > CAPTURE
  ASSERT(SIZEOF(.dev_capture) <= LENGTH(CAPTURE), "Development screenshot exceeds diagnostic reservation")
  .dev_usb_dma (NOLOAD) : { . += 0xe00; } > USB_DMA
#endif
#if !defined(LINNET_PROFILE_RELEASE)
  .dev_control (NOLOAD) : { . += 0x1000; } > CONTROL
#elif defined(LINNET_PLATFORM_CORE)
  .platform_control (NOLOAD) : { . += 0x1000; } > CONTROL
#endif
  /DISCARD/ : { *(.comment) *(.ARM.exidx*) *(.ARM.extab*) *(.note*) }
#ifdef LINNET_AUDIO
  /* Native codec arenas share the low8 MiB OS region. The independent Boot
   * recovery snapshot at30 MiB still has its unchanged1 MiB payload limit. */
  ASSERT(__stack_top <= 0x00400000, "Music resident image exceeds 4 MiB")
#else
  ASSERT(__stack_top <= 0x00100000, "Resident image exceeds 1 MiB")
#endif
  ASSERT(SIZEOF(.vectors) == 32, "ARM vector table must be 32 bytes")
}
