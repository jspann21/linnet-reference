/* M25 board wiring. Register provenance is in README.md alongside this target. */
#include "hal/pp502x/target.h"
#include "hal/api/power.h"
#include "hal/api/ata.h"
#include "hal/api/core.h"
#include "hal/api/platform.h"
#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))
#if defined(LINNET_IMAGE_OS)
static volatile bool click_active;
static volatile uint32_t click_started,click_count,click_max_us;
void ln_platform_click_stop(void){
    uint32_t flags=ln_core_irq_save();
    REG(0x7000a000u)=0;
    if(click_active){uint32_t elapsed=ln_time_us()-click_started;if(elapsed>click_max_us)click_max_us=elapsed;}
    click_active=false;
    ln_core_irq_restore(flags);
}
void ln_platform_click(void){
    /* PP5022 PWM0 drives the internal piezo independently of WM8758/I2S.
     * Drop overlapping feedback rather than extending a pulse indefinitely. */
    uint32_t flags=ln_core_irq_save();
    if(click_active){ln_core_irq_restore(flags);return;}
    REG(0x70000010u)&=~0xcu;REG(0x6000600cu)|=0x20000u;
    click_started=ln_time_us();click_active=true;++click_count;
    REG(0x7000a000u)=0x8080005bu;
    ln_core_wake_at(click_started+4000u);
    ln_core_irq_restore(flags);
}
void ln_platform_click_poll(uint32_t now){
    if(click_active&&now-click_started>=4000u)ln_platform_click_stop();
}
bool ln_platform_click_deadline(uint32_t *deadline){
    if(!click_active)return false;
    if(deadline)*deadline=click_started+4000u;return true;
}
void ln_platform_click_diagnostics(uint32_t out[4]){
    uint32_t flags=ln_core_irq_save();
    out[0]=REG(0x7000a000u);out[1]=click_count;out[2]=click_max_us;out[3]=click_active;
    ln_core_irq_restore(flags);
}
#endif
bool ln_target_battery_charging(void){return !(REG(0x6000d034u)&1u);}
uint8_t ln_target_power_sources(void){
    uint32_t pins=REG(0x6000d13cu);
    return ((pins&0x10u)?LINNET_POWER_USB:0u)|((pins&8u)?0u:LINNET_POWER_FIREWIRE);
}
void ln_target_power_prepare(struct ln_power_state *state){
    state->brightness=128u;state->backlight_on=(REG(0x6000d024u)&8u)!=0;
    REG(0x6000d004u)|=1u;REG(0x6000d014u)&=~1u;
    REG(0x6000d10cu)|=0x18u;REG(0x6000d11cu)&=~0x18u;
}
uint16_t ln_target_charge_limit_get(void){
    return REG(0x6000d12cu)&4u?0u:REG(0x6000d020u)&4u?500u:100u;
}
void ln_target_charge_limit_set(uint16_t milliamps){
    REG(0x6000d10cu)|=4u;REG(0x6000d11cu)|=4u;
    REG(0x6000d000u)|=4u;REG(0x6000d010u)|=4u;
    if(milliamps)REG(0x6000d12cu)&=~4u;else REG(0x6000d12cu)|=4u;
    if(milliamps==500u)REG(0x6000d020u)|=4u;else REG(0x6000d020u)&=~4u;
}
void ln_target_ata_power(bool on){
    if(on){
        REG(0x70000080u)&=~0x40000000u;
        (void)ln_core_delay_us(5000u);
        REG(0x6000600cu)|=0x02000000u;
        REG(0x6000d088u)=0;REG(0x6000d08cu)=0;
        REG(0x6000d100u)&=~0xbfu;REG(0x6000d108u)&=~0x1fu;
    }else{
        REG(0x6000600cu)&=~0x02000000u;
        (void)ln_core_delay_us(10u);
        REG(0x6000d088u)=0xffu;REG(0x6000d08cu)=0xffu;
        REG(0x6000d100u)|=0xbfu;REG(0x6000d108u)|=0x1fu;
        REG(0x70000080u)|=0x40000000u;
    }
}
void ln_target_ata_classify(const char *model,uint32_t *kind,uint32_t *rpm){
    /* Older IDENTIFY data omits rotation rate; match only the documented model. */
    static const char *const models[]={"TOSHIBA MK3008GAL","TOSHIBA MK8010GAH"};
    if(!model||!kind||!rpm)return;
    for(uint32_t n=0;n<sizeof(models)/sizeof(models[0]);++n){
        uint32_t i=0;while(models[n][i]&&model[i]==models[n][i])++i;
        if(!models[n][i]&&!model[i]){*kind=LN_ATA_MEDIA_ROTATING;*rpm=4200u;return;}
    }
}
void ln_target_input_prepare(void){
#if defined(LINNET_IMAGE_OS)
    ln_platform_click_stop();
#endif
}
void ln_target_switches_prepare(void){REG(0x6000d000u)|=0xa0u;REG(0x6000d010u)&=~0xa0u;}
uint32_t ln_target_switches_read(void){return REG(0x6000d030u);}
void ln_target_switches_rearm(uint32_t sample){
    REG(0x6000d060u)=(REG(0x6000d060u)&~0xa0u)|(~sample&0xa0u);
    REG(0x6000d070u)=0xa0u;REG(0x6000d050u)|=0xa0u;
}
void ln_target_backlight(bool on,uint8_t brightness){
    static bool initialized,enabled;
    static uint8_t level=16;
    REG(0x6000d004u)|=8u;REG(0x6000d014u)|=8u;
    REG(0x6000d00cu)|=0x80u;REG(0x6000d01cu)|=0x80u;
    REG(0x6000d10cu)|=0x80u;REG(0x6000d11cu)|=0x80u;
    if(!on||!brightness){
        REG(0x6000d12cu)&=~0x80u;REG(0x6000d02cu)&=~0x80u;REG(0x6000d024u)&=~8u;
        enabled=false;initialized=true;return;
    }
    if(!initialized||!enabled){
        REG(0x6000d024u)|=8u;REG(0x6000d02cu)|=0x80u;
        if(!ln_core_delay_us(10000u))return;
        level=16;enabled=true;initialized=true;
    }
    uint8_t desired=1u+((uint32_t)brightness*31u)/255u;
    while(level!=desired){
        uint32_t flags=ln_core_irq_save();
        REG(0x6000d02cu)&=~0x80u;
        bool ok=ln_core_delay_us(level<desired?10u:200u);
        REG(0x6000d02cu)|=0x80u;ln_core_irq_restore(flags);
        if(!ok||!ln_core_delay_us(10u))return;
        level+=level<desired?1:-1;
    }
    REG(0x6000d12cu)|=0x80u;
}

void ln_target_usb_prepare(void){REG(0x6000d11cu)&=~0x10u;REG(0x6000d10cu)|=0x10u;}
