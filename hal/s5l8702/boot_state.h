#pragma once
#include "boot/include/linnet_bytes.h"
#include "boot/include/linnet_boot.h"
enum { LN_S5L_BOOT_RECOVERY=0, LN_S5L_BOOT_NORMAL=1, LN_S5L_BOOT_DISK=2, LN_S5L_BOOT_ATTEMPT=3, LN_S5L_BOOT_ATTEMPT_DISK=4 };
static inline int ln_s5l_boot_mode(void) {
    const uint8_t *record=(const uint8_t *)(uintptr_t)0x22017b00u;
    return ln_read_le32(record)==0x54424e4cu && ln_read_le32(record+8)==ln_crc32(record,8)?(int)ln_read_le32(record+4):-1;
}
static inline void ln_s5l_boot_request(unsigned mode) {
    uint8_t *record=(uint8_t *)(uintptr_t)0x22017b00u;
    ln_write_le32(record,0);ln_write_le32(record+4,mode);
    ln_write_le32(record,0x54424e4cu);ln_write_le32(record+8,ln_crc32(record,8));
    uint32_t zero=0;__asm__ volatile("mcr p15,0,%0,c7,c10,4"::"r"(zero):"memory");
}
