#include "hal/api/platform.h"
#include "hal/api/display.h"
#include "hal/api/core.h"
#include "hal/s5l8702/registers.h"
#include "hal/s5l8702/board.h"
#include "ui/profiles/color320/boot_font.h"
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
static bool present(void){return ln_display_damage(0,0,LINNET_UI_WIDTH,LINNET_UI_HEIGHT)&&ln_display_present()&&ln_display_quiesce();}
bool ln_lcd_boot(void){
    if(!ln_lcd_fill(0x0841))return false;
    text(94,"Linnet",0xffff);text(150,"Starting",0xad75);return present();
}
bool ln_s5l_board_disk_screen(void){
    if(!ln_lcd_fill(0x0841))return false;
    text(72,"Disk Mode",0xffff);text(116,"Connected to computer",0xad75);
    text(160,"Eject before disconnecting",0xad75);return present();
}
bool ln_s5l_board_recovery_screen(void){
    if(!ln_lcd_fill(0x0841))return false;
    text(44,"Linnet Recovery",0xffff);
    text(94,"Select: start Linnet",0xad75);
    text(134,"Play: Disk Mode",0xad75);
    text(186,"Connect USB to repair",0xad75);return present();
}
bool ln_lcd_boot_selector(bool alternate,bool starting){return ln_lcd_fill(starting?0x07e0:alternate?0xfd20:0x001f);}
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
