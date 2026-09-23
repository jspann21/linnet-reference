#include "hal/api/platform.h"
#include "hal/api/display.h"
#include "hal/api/core.h"
#include "hal/s5l8702/registers.h"
#include "hal/s5l8702/board.h"
#include "ui/profiles/color320/boot_font.h"
#if defined(LINNET_IMAGE_OS) || defined(LINNET_IMAGE_BOOT)
#include "boot/include/linnet_boot_wordmark_320.h"
#endif
bool ln_lcd_fill(uint16_t color) {
    uint16_t *frame=ln_display_framebuffer();
    if(!frame){if(!ln_display_init())return false;frame=ln_display_framebuffer();}
    if(!ln_display_quiesce())return false;
    for(unsigned i=0;i<LINNET_DISPLAY_PIXELS;i++)frame[i]=color;
    if(!ln_display_damage(0,0,LINNET_UI_WIDTH,LINNET_UI_HEIGHT) || !ln_display_present())return false;
    return ln_display_quiesce();
}
static void text(unsigned top,const char *message,uint16_t color) {
    uint16_t *frame=ln_display_framebuffer();unsigned width=0;
    for(const char *p=message;*p;p++)if(*p>=32&&*p<=126)width+=advances[(unsigned)*p-32]*2u;
    unsigned left=width<LINNET_UI_WIDTH?(LINNET_UI_WIDTH-width)/2:0;
    for(;*message&&left<LINNET_UI_WIDTH;message++) {
        if(*message<32||*message>126)continue;unsigned glyph=(unsigned)*message-32;
        for(unsigned y=0;y<22&&top+y<LINNET_UI_HEIGHT;y++)
            for(unsigned x=0;x<22&&left+x<LINNET_UI_WIDTH;x++)
                if(glyphs[glyph][y/2]&(1u<<(x/2)))frame[(top+y)*LINNET_UI_WIDTH+left+x]=color;
        left+=advances[glyph]*2u;
    }
}
static void small_text(unsigned top,const char *message,uint16_t color) {
    uint16_t *frame=ln_display_framebuffer();unsigned width=0;
    for(const char *p=message;*p;p++)if(*p>=32&&*p<=126)width+=advances[(unsigned)*p-32];
    unsigned left=width<LINNET_UI_WIDTH?(LINNET_UI_WIDTH-width)/2:0;
    for(;*message&&left<LINNET_UI_WIDTH;message++) {
        if(*message<32||*message>126)continue;unsigned glyph=(unsigned)*message-32;
        for(unsigned y=0;y<11&&top+y<LINNET_UI_HEIGHT;y++)
            for(unsigned x=0;x<11&&left+x<LINNET_UI_WIDTH;x++)
                if(glyphs[glyph][y]&(1u<<x))frame[(top+y)*LINNET_UI_WIDTH+left+x]=color;
        left+=advances[glyph];
    }
}
static bool present(void){return ln_display_damage(0,0,LINNET_UI_WIDTH,LINNET_UI_HEIGHT)&&ln_display_present()&&ln_display_quiesce();}
bool ln_lcd_boot(void){
#if defined(LINNET_IMAGE_OS) || defined(LINNET_IMAGE_BOOT)
    uint16_t *frame=ln_display_framebuffer();
    if(!frame){if(!ln_display_init())return false;frame=ln_display_framebuffer();}
    if(!frame || !ln_display_quiesce())return false;
    unsigned pixel=0;
    for(unsigned run=0;run<sizeof ln_boot_runs/sizeof ln_boot_runs[0];run++){
        uint32_t packed=ln_boot_runs[run],index=packed&511u,count=packed>>9;
        if(!count || index>=sizeof ln_boot_palette/sizeof ln_boot_palette[0] ||
           count>LINNET_DISPLAY_PIXELS-pixel)return false;
        while(count--)frame[pixel++]=ln_boot_palette[index];
    }
    return pixel==LINNET_DISPLAY_PIXELS && present();
#else
    if(!ln_lcd_fill(0x0841))return false;
    text(94,"Linnet",0xffff);
    text(150,"Starting",0xad75);return present();
#endif
}
bool ln_lcd_boot_apple(void){
    if(!ln_lcd_fill(0xffff))return false;
    text(94,"Apple iPod Software",0x0000);text(150,"Starting",0x4208);return present();
}
bool ln_s5l_board_disk_screen(void){
    if(!ln_lcd_fill(0x39c7))return false;
    uint16_t *frame=ln_display_framebuffer();
    for(unsigned y=0;y<LINNET_UI_HEIGHT;y++){
        unsigned shade=y<24?y*2:y<110?190u-(y-24u):104u-(y-110u)/2u;
        unsigned red=shade*3u/4u,green=shade*7u/8u,blue=shade;
        uint16_t color=y<24?0x18e3u:(uint16_t)(((red>>3)<<11)|((green>>2)<<5)|(blue>>3));
        for(unsigned x=0;x<LINNET_UI_WIDTH;x++)frame[y*LINNET_UI_WIDTH+x]=color;
    }
    for(int y=-44;y<=44;y++)for(int x=-44;x<=44;x++){
        int distance=x*x+y*y;
        if(distance>44*44)continue;
        unsigned edge=(unsigned)distance*22u/(42u*42u),depth=(unsigned)(y+44)*42u/88u;
        unsigned red=255u-edge/2u-depth/5u,green=205u-edge-depth,blue=77u-edge/2u-depth/2u;
        uint16_t color=distance>42*42?0x9a60u:(uint16_t)(((red>>3)<<11)|((green>>2)<<5)|(blue>>3));
        frame[(unsigned)(104+y)*LINNET_UI_WIDTH+(unsigned)(160+x)]=color;
    }
    for(unsigned y=86;y<95;y++)for(unsigned x=146;x<174;x++)frame[y*LINNET_UI_WIDTH+x]=0x2104u;
    for(unsigned y=89;y<93;y++)for(unsigned x=141;x<179;x++)frame[y*LINNET_UI_WIDTH+x]=0x2104u;
    for(unsigned x=150;x<170;x++)frame[88u*LINNET_UI_WIDTH+x]=0xad55u;
    for(unsigned y=95;y<113;y++)for(unsigned x=157;x<163;x++)frame[y*LINNET_UI_WIDTH+x]=0x2104u;
    for(unsigned y=113;y<126;y++){
        unsigned half=(126u-y)*11u/13u;
        for(unsigned x=160u-half;x<=160u+half;x++)frame[y*LINNET_UI_WIDTH+x]=0x2104u;
    }
    small_text(6,"Linnet Disk Mode",0xffff);
    small_text(166,"Connected",0xffff);
    small_text(185,"Eject before disconnecting.",0xffff);
    return present();
}
bool ln_s5l_board_recovery_screen(void){
    if(!ln_lcd_fill(0x0841))return false;
    text(44,"Linnet Recovery",0xffff);
    text(94,"Select: start Linnet",0xad75);
    text(134,"Play: Disk Mode",0xad75);
    text(186,"Connect USB to repair",0xad75);return present();
}
bool ln_lcd_boot_menu(uint32_t available,uint32_t selected,bool starting){
    if(!ln_lcd_fill(0x0841u))return false;
    if(starting){
        text(74,"Starting",0xffffu);
        text(126,selected==3u?"Apple iPod Software":selected==2u?"Rockbox":"Linnet",0x5d9du);
        return present();
    }
    text(28,"Choose startup",0xffffu);
    if(!available)small_text(106,"Checking startup files",0xad75u);
    else{
        static const char *names[3]={"Linnet","Rockbox","Apple iPod Software"};
        uint32_t row=0;
        for(uint32_t choice=1u;choice<=3u;++choice){
            if(!(available&(1u<<(choice-1u))))continue;
            text(67u+row*39u,names[choice-1u],choice==selected?0xffffu:0x94b2u);
            if(choice==selected){
                uint16_t *frame=ln_display_framebuffer();
                uint32_t top=66u+row*39u;
                for(uint32_t y=top;y<top+25u;++y){frame[y*LINNET_UI_WIDTH+23u]=0x5d9du;
                    frame[y*LINNET_UI_WIDTH+24u]=0x5d9du;
                    frame[y*LINNET_UI_WIDTH+295u]=0x5d9du;
                    frame[y*LINNET_UI_WIDTH+296u]=0x5d9du;}
            }
            ++row;
        }
    }
    small_text(206,"Wheel: choose   Center: start",0xad75u);
    return present();
}
bool ln_lcd_fault(uint32_t reason,const uint8_t build[32]) {
    (void)build;
    if(!ln_lcd_fill(0x7800))return false;
    char code[]="Error 00000000";const char digits[]="0123456789ABCDEF";
    for(unsigned i=0;i<8;i++)code[6+i]=digits[(reason>>(28-i*4))&15];
    text(94,"Startup needs recovery",0xffff);text(150,code,0xffff);return present();
}
void ln_lcd_diagnostics(uint32_t out[8]) {
    if(!out)return;
    out[0]=LN_REG(0x38300000u);out[1]=LN_REG(0x3830001cu);out[2]=ln_display_init_error();
    out[3]=ln_display_busy();out[4]=ln_display_snapshot_crc32();
    out[5]=LN_REG(0x3cf000c4u);out[6]=LN_REG(0x38300020u);out[7]=ln_time_us();
}
