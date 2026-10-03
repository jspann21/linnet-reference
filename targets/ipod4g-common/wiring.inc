/* Board wiring shared by Q21 and P98, not the PortalPlayer family. */
#include "hal/api/power.h"
uint8_t ln_target_power_sources(void) {
    return ((REG(0x6000d03cu)&8u)?LINNET_POWER_USB:0u)|
           ((REG(0x6000d038u)&4u)?0u:LINNET_POWER_FIREWIRE);
}
void ln_target_power_prepare(struct ln_power_state *state) {
    state->brightness=(uint8_t)(REG(0x7000a010u)>>16);
    state->backlight_on=(REG(0x6000d024u)&8u)!=0;
    REG(0x7000008cu)|=1u;REG(0x70000084u)&=~1u;
}
uint16_t ln_target_charge_limit_get(void) {
    uint32_t value=REG(0x70000080u);
    return value&0x08000000u?0u:value&0x40u?500u:100u;
}
void ln_target_charge_limit_set(uint16_t milliamps) {
    /* Caller must supply the negotiated USB power budget before selecting 500. */
    REG(0x70000084u) |= 0x08000040u;
    uint32_t value = REG(0x70000080u) & ~0x08000040u;
    if (!milliamps) value |= 0x08000000u;
    if (milliamps == 500) value |= 0x40u;
    REG(0x70000080u) = value;
}
void ln_target_backlight(bool on,uint8_t brightness) {
    REG(0x6000d804u) = 0x0c0cu;
    REG(0x70000084u) &= ~0x02000000u;
    REG(0x6000600cu) |= 0x20000u;
    REG(0x7000a010u) = 0x80000000u | ((uint32_t)(on ? brightness : 0u) << 16);
    REG(0x6000d824u) = on ? 0x0808u : 0x0800u;
}
void ln_target_ata_power(bool on) {
    if(on){
        REG(0x6000d124u)&=~4u;REG(0x6000d100u)&=~0xbfu;REG(0x6000d108u)&=~0x1fu;
        REG(0x6000600cu)|=0x02000000u;
    }else{
        REG(0x6000600cu)&=~0x02000000u;REG(0x6000d124u)|=4u;
        REG(0x6000d100u)|=0xbfu;REG(0x6000d108u)|=0x1fu;
    }
}
void ln_target_switches_prepare(void) {
    REG(0x6000d000u)|=0xa0u;REG(0x6000d010u)&=~0xa0u;
}
uint32_t ln_target_switches_read(void) { return REG(0x6000d030u); }
void ln_target_switches_rearm(uint32_t sample) {
    REG(0x6000d060u)=(REG(0x6000d060u)&~0xa0u)|(~sample&0xa0u);
    REG(0x6000d070u)=0xa0u;REG(0x6000d050u)|=0xa0u;
}

void ln_target_usb_prepare(void){REG(0x6000d01cu)&=~8u;REG(0x6000d00cu)|=8u;}
