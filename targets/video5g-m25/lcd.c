/* BCM2722 mailbox scanout, implemented independently from the documented bus.
 * The Apple ROM must have initialized VMCS. No copied firmware is embedded. */
#include "targets/video5g-m25/lcd.h"
#include "hal/api/platform.h"
#include "ui/profiles/color320/boot_font.h"
#if defined(LINNET_IMAGE_BOOT)
#include "boot/include/linnet_boot_wordmark_320.h"
#endif
#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define HALF(a) (*(volatile uint16_t *)(uintptr_t)(a))
static uint32_t writes,commands,failures,last_error;
static bool wait(uint32_t address,uint32_t mask){
    uint32_t started=ln_time_us();
    for(uint32_t i=0;i<10000u;++i){
        if(HALF(address)&mask)return true;
        if(ln_time_us()-started>=1000u)break;
    }
    ++failures;last_error=address;return false;
}
static bool read_word(uint32_t address,uint32_t *value){
    if(!wait(0x30020000u,1u))return false;
    REG(0x30020000u)=address;
    if(!wait(0x30030000u,0x10u))return false;
    *value=REG(0x30000000u);return true;
}
static bool address(uint32_t value){
    REG(0x30010000u)=value;return wait(0x30030000u,2u);
}
bool ln_m25_lcd_runtime_header(uint32_t words[4]){
    if(!words)return false;
    /* Fixed read-only identity window shared by boot VMCS and retail VMCS.
     * A display acknowledgement alone does not identify the media runtime. */
    for(uint32_t i=0;i<4u;++i)
        if(!read_word(0x1f0u+i*4u,&words[i]))return false;
    return true;
}
bool ln_m25_bcm_read(uint32_t at,uint32_t *words,uint32_t count){
    if(!words||(at&3u)||!count||count>32u)return false;
    for(uint32_t i=0;i<count;++i)if(!read_word(at+i*4u,&words[i]))return false;
    return true;
}
bool ln_m25_bcm_write(uint32_t at,const uint32_t *words,uint32_t count){
    if(!words||(at&3u)||((uintptr_t)words&3u)||!count||count>1024u)return false;
    if(!address(at))return false;
    for(uint32_t i=0;i<count;++i)REG(0x30000000u)=words[i];
    return true;
}
bool ln_m25_lcd_init(void){
    /* Keep the ROM's BCM power and bus setup. Never power-cycle inherited VMCS. */
    if(!(REG(0x70000080u)&0x4000u)){last_error=1;return false;}
    REG(0x70000084u)|=0xc000u;REG(0x6000d008u)&=~0x80u;
    REG(0x6000d008u)|=0x40u;REG(0x6000d018u)&=~0x40u;
    REG(0x70000084u)&=~1u;
    uint32_t status;return read_word(0x1f8u,&status);
}
bool ln_m25_lcd_ready(bool *ready){
    uint32_t status;if(!ready||!read_word(0x1f8u,&status))return false;
    *ready=status!=0xffff0000u&&status!=0xffffu;return true;
}
bool ln_m25_lcd_write(uint32_t pixel,const uint16_t *data,uint32_t count){
    if(!data||!count||(pixel&1u)||(count&1u)||pixel>=76800u||count>76800u-pixel)return false;
    if(!address(0xe0000u+pixel*2u))return false;
    if(!((uintptr_t)data&3u)){
        typedef uint32_t pixel_pair __attribute__((may_alias));
        const pixel_pair *pairs=(const pixel_pair *)data;
        for(uint32_t i=0;i<count/2u;++i)REG(0x30000000u)=pairs[i];
    }else{
        for(uint32_t i=0;i<count;i+=2u)REG(0x30000000u)=(uint32_t)data[i]|((uint32_t)data[i+1u]<<16);
    }
    writes+=count/2u;return true;
}
bool ln_m25_lcd_commit(void){
    if(!address(0x1f8u))return false;
    REG(0x30000000u)=0xffff0000u;HALF(0x30030000u)=0x31u;++commands;return true;
}
static bool await_ready(void){
    uint32_t started=ln_time_us();
    for(uint32_t budget=0;budget<100000u;++budget){
        bool ready;if(!ln_m25_lcd_ready(&ready))return false;if(ready)return true;
        if(ln_time_us()-started>=500000u)break;
    }
    ++failures;last_error=2;return false;
}
bool ln_lcd_fill(uint16_t color){
    if(!ln_m25_lcd_init()||!await_ready())return false;
    uint16_t row[320];for(uint32_t x=0;x<320u;++x)row[x]=color;
    for(uint32_t y=0;y<240u;++y)if(!ln_m25_lcd_write(y*320u,row,320u))return false;
    return ln_m25_lcd_commit()&&await_ready();
}
static void text_row(uint16_t row[320],uint32_t y,uint32_t top,const char *text,uint16_t color){
    if(y<top||y>=top+22u)return;
    uint32_t width=0;for(const char *p=text;*p;++p)if(*p>=32&&*p<=126)width+=advances[(unsigned)*p-32]*2u;
    uint32_t x=width<320u?(320u-width)/2u:0;
    for(;*text&&x<320u;++text){
        if(*text<32||*text>126)continue;
        uint32_t glyph=(unsigned)*text-32,bits=glyphs[glyph][(y-top)/2u];
        for(uint32_t i=0;i<22u&&x+i<320u;++i)if(bits&(1u<<(i/2u)))row[x+i]=color;
        x+=advances[glyph]*2u;
    }
}
static bool message(const char *title,const char *detail,uint16_t accent){
    if(!ln_m25_lcd_init()||!await_ready())return false;
    uint16_t row[320];
    for(uint32_t y=0;y<240u;++y){
        for(uint32_t x=0;x<320u;++x)row[x]=(y>=132u&&y<134u&&x>=40u&&x<280u)?accent:0x0841u;
        text_row(row,y,94u,title,0xffffu);text_row(row,y,150u,detail,0xad75u);
        if(!ln_m25_lcd_write(y*320u,row,320u))return false;
    }
    return ln_m25_lcd_commit()&&await_ready();
}
#if defined(LINNET_IMAGE_BOOT)
bool ln_lcd_boot(void){
    if(!ln_m25_lcd_init()||!await_ready())return false;
    uint16_t row[320],pixel=0;uint32_t run=0,left=0;
    for(uint32_t y=0;y<240u;++y){
        for(uint32_t x=0;x<320u;++x){
            if(!left){
                if(run>=sizeof ln_boot_runs/sizeof ln_boot_runs[0])return false;
                uint32_t packed=ln_boot_runs[run++],index=packed&511u;left=packed>>9;
                if(!left||index>=sizeof ln_boot_palette/sizeof ln_boot_palette[0])return false;
                pixel=ln_boot_palette[index];
            }
            row[x]=pixel;--left;
        }
        if(!ln_m25_lcd_write(y*320u,row,320u))return false;
    }
    if(left||run!=sizeof ln_boot_runs/sizeof ln_boot_runs[0])return false;
    return ln_m25_lcd_commit()&&await_ready();
}
bool ln_lcd_boot_apple(void){return ln_lcd_fill(0xffffu);}
bool ln_lcd_boot_selector(bool alternative,bool starting){(void)alternative;(void)starting;return ln_lcd_boot();}
#endif
bool ln_lcd_fault(uint32_t reason,const uint8_t build[32]){
    (void)build;char detail[]="Fault 00000000";const char digits[]="0123456789ABCDEF";
    for(uint32_t i=0;i<8u;++i)detail[6u+i]=digits[(reason>>((7u-i)*4u))&15u];
    return message("Linnet",detail,0xf800u);
}
#if !defined(LINNET_PROFILE_RELEASE)
void ln_lcd_diagnostics(uint32_t out[8]){
    if(!out)return;
    uint32_t words[8]={0x3544434cu,writes,commands,failures,last_error,
        HALF(0x30030000u),REG(0x70000080u),REG(0x70000084u)};
    for(uint32_t i=0;i<8u;++i)out[i]=words[i];
}
#endif
