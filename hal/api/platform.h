#ifndef LINNET_HAL_PLATFORM_H
#define LINNET_HAL_PLATFORM_H
#include <stdbool.h>
#include <stdint.h>
#include "linnet_target.h"
uint32_t ln_time_us(void);
/* Return a CPU address that bypasses cache for target SDRAM, when required. */
uintptr_t ln_platform_uncached_address(uintptr_t address);
bool ln_lcd_fill(uint16_t color);
#if defined(LINNET_TARGET_PHOTO4G_P98)
uint32_t ln_lcd_panel_type(void);
#endif
#if defined(LINNET_IMAGE_BOOT)
bool ln_lcd_boot(void);
bool ln_lcd_boot_selector(bool rockbox, bool starting);
#endif
/* Bounded, standalone field fault display, including release Boot. */
bool ln_lcd_fault(uint32_t reason,const uint8_t build_id[32]);
#if !defined(LINNET_PROFILE_RELEASE)
void ln_lcd_diagnostics(uint32_t output[8]);
#endif
void ln_platform_quiesce(void);
bool ln_platform_dma_idle(void);
bool ln_platform_audio_idle(void);
#if defined(LINNET_PLATFORM_CORE) && defined(LINNET_IMAGE_BOOT)
/* Early Boot only, before transport owns ARC/IRAM. Nonzero leaves clock policy
 * unchanged. Known native USB state may use canonical enable/reset pulses;
 * never gates module clocks off or touches USB descriptors. */
/* 0 ready; BTT4 skip reason 7..20 otherwise. */
uint32_t ln_platform_boot_clock_ready(void);
#endif
void ln_watchdog_feed(void);
bool ln_watchdog_expired(void);
_Noreturn void ln_panic(uint32_t reason, uint32_t pc, uint32_t status);
_Noreturn void ln_main(void);
#endif
