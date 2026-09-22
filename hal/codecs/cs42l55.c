/* CS42L55 playback configuration: Cirrus DS773F1, sections 4.11/4.13/6.
 * Register compensation is manufacturer-specified data. */
#include "codec.h"
#include "hal/api/core.h"
static uint8_t rate_value(uint32_t rate) {
    switch(rate) {
    case 8000:return 0x1d;case 11025:return 0x1b;case 12000:return 0x19;
    case 16000:return 0x15;case 22050:return 0x13;case 24000:return 0x11;
    case 32000:return 0x0d;case 44100:return 0x0b;case 48000:return 9;
    default:return 0;
    }
}
bool ln_codec_rate_supported(uint32_t rate){return rate_value(rate)!=0;}
bool ln_codec_rate(ln_codec_writer write,uint32_t rate) {
    uint8_t value=rate_value(rate);return value && write(5,value);
}
bool ln_codec_volume(ln_codec_writer write,int32_t value) {
    if(value<-1020 || value>0)return false;
    /* Exact unsigned division by five without an ARM runtime helper. */
    int32_t steps=-(int32_t)(((uint64_t)(4-value)*0xcccccccdu)>>34);
    return write(0x18,(uint8_t)steps) && write(0x19,(uint8_t)steps);
}
bool ln_codec_lineout(ln_codec_writer write,bool enabled) {
    return write(0x1c,enabled?0:0xc0) && write(0x1d,enabled?0:0xc0) && write(3,enabled?0xaa:0xaf);
}
bool ln_codec_mute(ln_codec_writer write,bool mute) {
    if(mute)return write(0x0f,3) && write(0x1a,0xc0) && write(0x1b,0xc0);
    return write(0x1a,0) && write(0x1b,0) && write(0x0f,0);
}
bool ln_codec_off(ln_codec_writer write) {
    bool muted=ln_codec_mute(write,true),line=ln_codec_lineout(write,false),power=write(2,0x0f);
    return muted && line && power;
}
bool ln_codec_init(ln_codec_writer write,uint32_t rate) {
    if(!ln_codec_rate_supported(rate) || !write(2,0x0f))return false;
    static const uint8_t compensation[][2]={
        {0,0x99},{0x2e,0x30},{0x32,7},{0x33,0xff},{0x34,0xf8},{0x35,0xdc},
        {0x36,0xfc},{0x37,0xac},{0x3a,0xf8},{0x3c,0xd3},{0x3d,0x23},
        {0x3e,0x81},{0x3f,0x46},{0,0}};
    for(unsigned i=0;i<sizeof(compensation)/sizeof(compensation[0]);i++)
        if(!write(compensation[i][0],compensation[i][1]))return false;
    if(!ln_codec_mute(write,true) || !ln_codec_lineout(write,false) ||
       !write(4,0x2e) || !ln_codec_rate(write,rate) || !write(7,0x1c) ||
       !write(8,0) || !write(0x0b,0) || !write(0x0c,0) ||
       !write(6,0x30) || !ln_codec_volume(write,-180) || !write(2,6))return false;
    /* Leave both channels muted; the audio owner unmutes after priming. */
    return ln_core_delay_us(75000);
}
