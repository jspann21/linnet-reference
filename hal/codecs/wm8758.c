/* Independent WM8758 playback configuration for M25. No Rockbox runtime. */
#include "hal/codecs/codec.h"
#include "hal/api/core.h"
bool ln_codec_rate_supported(uint32_t rate){
    switch(rate){case 8000:case 11025:case 12000:case 16000:case 22050:
    case 24000:case 32000:case 44100:case 48000:return true;default:return false;}
}
bool ln_codec_rate(ln_codec_writer write,uint32_t rate){
    uint16_t divider,filter;
    switch(rate){
    case 44100:case 48000:divider=2;filter=0;break;
    case 32000:divider=3;filter=1;break;
    case 22050:case 24000:divider=4;filter=2;break;
    case 16000:divider=5;filter=3;break;
    case 11025:case 12000:divider=6;filter=4;break;
    case 8000:divider=7;filter=5;break;default:return false;
    }
    /* A 12 MHz reference yields 22.5792 or 24.576 MHz PLL output. */
    bool family44=rate==44100||rate==22050||rate==11025;
    uint32_t fraction=family44?0x86c226u:0x3126e9u;
    return write(0x24,family44?0x17:0x18)&&write(0x25,(fraction>>18)&63u)&&
        write(0x26,(fraction>>9)&511u)&&write(0x27,fraction&511u)&&
        write(6,0x105u|(divider<<5))&&write(7,1u|(filter<<1));
}
bool ln_codec_volume(ln_codec_writer write,int32_t value){
    if(value < -730 || value > 0)return false;
    int32_t db=(value-9)/10;
    uint16_t amp=db < -57?0u:(uint16_t)(db+57);
    uint16_t dac=db < -57?(uint16_t)(255+2*(db+57)):255u;
    return write(0x0b,dac)&&write(0x0c,0x100u|dac)&&
        write(0x34,0x80u|amp)&&write(0x35,0x180u|amp);
}
bool ln_codec_mute(ln_codec_writer write,bool mute){return write(0x0a,mute?0x40u:8u);}
bool ln_codec_off(ln_codec_writer write){
    bool mute=ln_codec_mute(write,true),p2=write(2,0),p3=write(3,0),p1=write(1,0);
    return mute&&p2&&p3&&p1;
}
bool ln_codec_init(ln_codec_writer write,uint32_t rate){
    if(!ln_codec_rate_supported(rate)||!write(0,0)||!ln_codec_mute(write,true))return false;
    if(!write(0x3d,0x100)||!write(0x31,0x187)||!write(0x34,0x140)||
       !write(0x35,0x140)||!write(0x36,0x140)||!write(0x37,0x140)||
       !write(0x38,0x40)||!write(0x39,0x40)||!write(2,0x180)||
       !write(0x2a,4)||!write(3,15)||!write(1,0x2f)||!write(4,0x10)||
       !ln_codec_rate(write,rate)||!write(0x32,1)||!write(0x33,1))return false;
    if(!ln_core_delay_us(10000)||!ln_core_delay_us(10000))return false;
    return write(0x2a,0)&&write(1,0x2e)&&write(0x3d,0);
}
