#include <stdbool.h>
#include <stdint.h>
#include "hal/pp5020/ata.h"

#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))

bool ln_target_battery_charging(void)
{
    /* Fourth-generation monochrome boards expose active-low charge on B0. */
    return !(REG(0x6000d034u) & 1u);
}

void ln_target_ata_classify(const char *model,uint32_t *media_kind,uint32_t *rotation_rpm)
{
    static const char original[]="TOSHIBA MK2006GAL";
    uint32_t i=0;
    if(!model||!media_kind||!rotation_rpm)return;
    while(original[i]&&model[i]==original[i])++i;
    if(original[i]||model[i])return;
    *media_kind=LN_ATA_MEDIA_ROTATING;
    *rotation_rpm=4200u;
}
