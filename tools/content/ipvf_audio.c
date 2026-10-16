#include <stdint.h>
#include "services/video/ipvf/ima_lookup.h"
#if defined(_WIN32)
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif
static const uint16_t steps[89]={
    7,8,9,10,11,12,13,14,16,17,19,21,
    23,25,28,31,34,37,41,45,50,55,60,66,
    73,80,88,97,107,118,130,143,157,173,190,209,
    230,253,279,307,337,371,408,449,494,544,598,658,
    724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,
    2272,2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,
    7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,
    22385,24623,27086,29794,32767
};
static int32_t sample(const uint8_t *p){
    unsigned value=(unsigned)p[0]|((unsigned)p[1]<<8);
    return value&32768u?(int)value-65536:(int)value;
}
static uint32_t nibble(int32_t target,int32_t *predictor,uint32_t *index){
    int32_t difference=target-*predictor;
    uint32_t code=0,step=steps[*index];
    if(difference<0){code=8;difference=-difference;}
    if((unsigned)difference>=step){code|=4;difference-=(int)step;}
    if((unsigned)difference>=(step>>1)){code|=2;difference-=(int)(step>>1);}
    if((unsigned)difference>=(step>>2))code|=1;
    uint32_t entry=ima_lookup[(*index<<3)|(code&7u)];
    int32_t delta=(int32_t)(entry>>8);
    int32_t value=*predictor+(code&8u?-delta:delta);
    *predictor=value>32767?32767:value< -32768?-32768:value;
    *index=entry&255u;
    return code;
}
/* PCM and output are disjoint. Caller owns both buffers for the entire call.
 * state receives next channel indices and silence/mono/stereo (0/1/2). */
EXPORT int32_t ln_ipvf_encode_audio(const uint8_t *pcm,uint32_t input_bytes,uint32_t frames,
    uint32_t left_index,uint32_t right_index,uint8_t *out,uint32_t capacity,uint32_t state[3]){
    if(!pcm||!out||!state||!frames||frames>UINT32_MAX/4u||
       input_bytes!=frames*4u||left_index>88u||right_index>88u||capacity<frames+7u)return -1;
    uint32_t nonzero=0,mono=1;
    for(uint32_t n=0;n<frames;++n){const uint8_t *p=pcm+n*4u;
        nonzero|=(unsigned)p[0]|p[1]|p[2]|p[3];
        mono&=(p[0]==p[2]&&p[1]==p[3]);}
    state[0]=left_index;state[1]=right_index;state[2]=0;
    if(!nonzero)return 0;
    int32_t left=sample(pcm),right=sample(pcm+2);
    out[0]=pcm[0];out[1]=pcm[1];out[2]=(uint8_t)left_index;out[3]=0;
    if(mono){
        for(uint32_t n=1;n<frames;++n){
            unsigned code=nibble(sample(pcm+n*4u),&left,&left_index);
            if(n&1u)out[4u+(n-1u)/2u]=(uint8_t)code;
            else out[4u+(n-1u)/2u]|=(uint8_t)(code<<4);
        }
        state[0]=state[1]=left_index;state[2]=1;
        return (int)(4u+frames/2u);
    }
    out[4]=pcm[2];out[5]=pcm[3];out[6]=(uint8_t)right_index;out[7]=0;
    for(uint32_t n=1;n<frames;++n){
        unsigned a=nibble(sample(pcm+n*4u),&left,&left_index);
        unsigned b=nibble(sample(pcm+n*4u+2u),&right,&right_index);
        out[7u+n]=(uint8_t)(a|(b<<4));
    }
    state[0]=left_index;state[1]=right_index;state[2]=2;
    return (int)(frames+7u);
}
