#include <stdbool.h>
#include <stdint.h>
#include "hal/api/ata.h"
#include "hal/api/platform.h"
#include "hal/pp502x/target.h"

#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))

bool ln_target_battery_charging(void)
{
    /* P98 exposes the active-low charger state through GPO32 input bit 0. */
    REG(0x70000088u) = 0;
    return !(REG(0x70000088u) & 1u);
}

void ln_target_ata_classify(const char *model,uint32_t *media_kind,uint32_t *rotation_rpm)
{
    static const char original[]="TOSHIBA MK3006GAL";
    uint32_t i=0;
    if(!model||!media_kind||!rotation_rpm)return;
    while(original[i]&&model[i]==original[i])++i;
    if(original[i]||model[i])return;
    *media_kind=LN_ATA_MEDIA_ROTATING;
    *rotation_rpm=4200u;
}

void ln_target_input_prepare(void) {}

#include "targets/ipod4g-common/wiring.inc"
