#include "settings.h"
#include "boot/include/linnet_boot.h"
static void put(uint8_t*p,uint32_t v){for(uint32_t i=0;i<4;++i)p[i]=(uint8_t)(v>>(i*8));}
static uint32_t get(const uint8_t*p){return(uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
/* MSET: magic, queue byte count, queue record, profile record and envelope CRC.
 * Each embedded record retains its own validation. Decode publishes both values
 * atomically. */
uint32_t ln_music_settings_encode(const struct ln_queue*q,const struct ln_music_profile*p,uint8_t*out,uint32_t cap){
    if(!q||!p||!out||cap<44)return 0;
    uint32_t n=ln_queue_encode(q,out+8,cap-44);if(!n)return 0;
    if(!ln_music_profile_encode(p,out+8+n))return 0;
    put(out,0x5445534du);put(out+4,n);put(out+40+n,ln_crc32(out,40+n));return 44+n;
}
bool ln_music_settings_decode(struct ln_queue*q,struct ln_music_profile*p,const uint8_t*in,uint32_t bytes){
    if(!q||!p||!in)return false;struct ln_queue saved;struct ln_music_profile profile;
    if(bytes<44||get(in)!=0x5445534du)return false;
    uint32_t n=get(in+4);if(n!=bytes-44||get(in+40+n)!=ln_crc32(in,40+n)||
        !ln_queue_decode(&saved,in+8,n)||!ln_music_profile_decode(&profile,in+8+n,32))return false;
    *q=saved;*p=profile;return true;
}
