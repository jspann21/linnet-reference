/* WM8975 policy extracted from Linnet's verified fourth-generation sink. */
#include "hal/codecs/codec.h"
#include "hal/api/core.h"
bool ln_codec_rate(ln_codec_writer write,uint32_t rate) {
    uint16_t sample;
    switch(rate){case 44100:sample=0x63;break;case 48000:sample=0x41;break;
        case 22050:sample=0x77;break;case 32000:sample=0x59;break;
        /* The reference's unused12 kHz constant0x61 measures44.1 kHz on
         * this device. USB SR=01000 selects12 kHz;11001 selects11.025 kHz. */
        case 8000:sample=0x4d;break;case 12000:sample=0x51;break;
        case 11025:sample=0x73;break;
        case 16000:sample=0x55;break;case 24000:sample=0x79;break;
        case 88200:sample=0x7f;break;case 96000:sample=0x5d;break;default:return false;}
    return write(8,sample);
}
static bool supported(uint8_t reg,uint16_t value){(void)reg;(void)value;return true;}
bool ln_codec_rate_supported(uint32_t rate){return ln_codec_rate(supported,rate);}
bool ln_codec_volume(ln_codec_writer write,int32_t value){
    if(value < -730 || value > 0)return false;
    uint16_t code=(uint16_t)(121+(value-9)/10);
    return write(2,0x80u|code)&&write(3,0x180u|code);
}
bool ln_codec_lineout(ln_codec_writer write,bool enabled){(void)write;(void)enabled;return true;}
bool ln_codec_mute(ln_codec_writer write,bool mute){return write(5,mute?8u:0u);}
bool ln_codec_off(ln_codec_writer write){
    bool muted=write(5,8),p2=write(0x1a,0),p1=write(0x19,0);return muted&&p2&&p1;
}
bool ln_codec_init(ln_codec_writer write,uint32_t rate){
    return write(0xf,0)&&write(5,8)&&ln_codec_volume(write,-400)&&write(0x19,0x1c0)&&
        ln_core_delay_us(10000)&&ln_core_delay_us(10000)&&write(0x19,0xc0)&&
        write(0x1a,0x1e0)&&write(7,0x42)&&ln_codec_rate(write,rate)&&
        write(0x22,0x100)&&write(0x23,0)&&write(0x24,0)&&write(0x25,0x100);
}
