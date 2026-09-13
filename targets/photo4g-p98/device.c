#include <stdbool.h>
#include <stdint.h>
#include "hal/pp5020/ata.h"

#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))

bool ln_target_battery_charging(void)
{
    /* P98 exposes the active-low charger state through GPO32 input bit 0. */
    REG(0x70000088u) = 0;
    return !(REG(0x70000088u) & 1u);
}

void ln_target_ata_classify(const char *model,uint32_t *media_kind,uint32_t *rotation_rpm)
{
    (void)model;(void)media_kind;(void)rotation_rpm;
}
