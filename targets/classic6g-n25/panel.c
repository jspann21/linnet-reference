#include "panel.h"
#include "board.h"
#include "hal/s5l8702/lcd_bus.h"
#include "hal/s5l8702/i2c.h"
#include "hal/s5l8702/registers.h"
extern uint32_t ln_time_us(void);
static uint32_t phase,deadline,pixel,bar,bar_pixel;
static const uint16_t *frame;
static bool color_bars;
static bool send(uint8_t command,const uint8_t *data,unsigned count) {
    if(!ln_s5l_lcd_command(command))return false;
    for(unsigned i=0;i<count;i++)if(!ln_s5l_lcd_data(data[i]))return false;
    return true;
}
static bool pmu(uint8_t reg,uint8_t value) {
    return ln_s5l_i2c_write(0,0x73,reg,&value,1);
}
static bool begin_frame(void) {
    static const uint8_t columns[]={0,0,1,0x3f},rows[]={0,0,0,0xef};
    if(!ln_s5l_lcd_mode(0x80000c20u) || !send(0x2a,columns,4) ||
       !send(0x2b,rows,4) || !send(0x2c,0,0) || !ln_s5l_lcd_mode(0x80100db0u))return false;
    pixel=0;phase=2;return true;
}
bool ln_n25_panel_present(const uint16_t *pixels) {
    if(phase!=3 || !pixels)return false;
    frame=pixels;
    if(begin_frame()){
#if defined(LINNET_IMAGE_OS)
        if(!ln_s5l_lcd_dma_begin(pixels,320u*240u)){phase=0xffffffffu;return false;}
        phase=4;
#endif
        return true;
    }
    phase=0xffffffffu;return false;
}
bool ln_n25_panel_start(bool diagnostic) {
    color_bars=diagnostic;
    phase=0;pixel=0;bar=0;bar_pixel=0;frame=0;
    if(((LN_REG(0x3cf000c4u)>>4)&3u)!=1)return false;
    if(!ln_n25_lcd_power())return false;
    LN_REG(0x38300020u)=0x33;
    if(!ln_s5l_lcd_mode(0x80000c20u))return false;
    /* Establish the same controller state after ROM, OS and RAM handoffs.
     * A repeated Sleep Out alone does not reset an already awake panel. */
    if(!send(0x01,0,0))return false;
    deadline=ln_time_us()+120000u;phase=5;return true;
}
bool ln_n25_panel_adopt(void) {
    if(((LN_REG(0x3cf000c4u)>>4)&3u)!=1 ||
       (LN_CLOCK_GATE0&2u) || LN_REG(0x38300000u)!=0x80100db0u ||
       !(LN_REG(0x3830001cu)&2u))return false;
    phase=3;pixel=bar=bar_pixel=0;frame=0;color_bars=false;return true;
}
static bool configure(void) {
    /* N25 panel-1 electrical timing and gamma register values. These are
     * panel configuration data, separate from the S5L transfer driver. */
    static const uint8_t timing[]={0x3a,0x3a,0x80,0x80,0x0a,0x0a,0x0a,0x0a,
        0x0a,0x0a,0x0a,0x0a,0x3c,0x30,0x0f,0,1,0x54,6,0x66,0x66};
    static const uint8_t drive[]={0x14,0x59,0,0x15,0x57,0x27,4,0x85,
        0x14,0x59,0,0x15,0x57,0x27,4,0x85,0x14,9,0x15,0x57,0x27,4,5,
        0x14,9,0x15,0x57,0x27,4,5};
    static const uint8_t gamma[3][13]={
        {0,0,0,5,0x0b,0x12,0x16,0x1f,0x25,0x22,0x24,0x29,0x1c},
        {8,1,1,6,0x0b,0x11,0x15,0x1f,0x27,0x26,0x29,0x2f,0x1e},
        {7,1,1,5,9,0x0f,0x13,0x1e,0x26,0x25,0x28,0x2e,0x1e}};
    uint8_t value=0xd8;
    if(!send(0xb0,timing,sizeof(timing)) || !send(0xb8,&value,1) ||
       !send(0xb1,drive,sizeof(drive)))return false;
    value=1;if(!send(0xd2,&value,1))return false;
    for(unsigned i=0;i<6;i++)if(!send((uint8_t)(0xe0+i),gamma[i%3],13))return false;
    value=6;if(!send(0x3a,&value,1))return false;
    value=0;if(!send(0xc2,&value,1) || !send(0x35,&value,1) || !send(0x11,0,0))return false;
    deadline=ln_time_us()+60000u;phase=1;return true;
}
uint32_t ln_n25_panel_service(uint32_t pixels) {
    if(pixels>512)pixels=512;
    if(phase==5){
        if((int32_t)(ln_time_us()-deadline)<0)return phase;
        if(!configure())goto fail;
    }
#if defined(LINNET_IMAGE_OS)
    if(phase==4){int result=ln_s5l_lcd_dma_poll();if(result<0)goto fail;if(result>0)phase=3;return phase;}
#endif
    if(phase==1) {
        if((int32_t)(ln_time_us()-deadline)<0)return phase;
        /* Memory Access Control is only reliable after Sleep Out has settled.
         * Program it explicitly so cold NOR boot and warm RAM boot do not
         * inherit different scan directions from the previous firmware. */
        uint8_t orientation=0;
        if(!send(0x36,&orientation,1) || !send(0x13,0,0) ||
           !send(0x29,0,0) || !begin_frame())goto fail;
    }
    if(phase==2) {
        static const uint16_t colors[]={0xffff,0xffe0,0x07ff,0x07e0,0xf81f,0xf800,0x001f,0};
        for(unsigned i=0;i<pixels && pixel<320u*240u;i++,pixel++) {
            if(!ln_s5l_lcd_data(frame?frame[pixel]:color_bars?colors[bar]:0x0841))goto fail;
            if(++bar_pixel==40){bar_pixel=0;bar=(bar+1)&7;}
        }
        if(pixel==320u*240u) {
            if(!pmu(0x2a,5) || !pmu(0x2b,0x14) || !pmu(0x28,0x20) || !pmu(0x29,1))goto fail;
            phase=3;
        }
    }
    return phase;
fail:phase=0xffffffffu;return phase;
}
uint32_t ln_n25_panel_poll(void){return ln_n25_panel_service(256);}
