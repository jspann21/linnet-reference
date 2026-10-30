#ifndef LINNET_CLICK_PCM_H
#define LINNET_CLICK_PCM_H
#include <stdbool.h>
#include <stdint.h>

/* Linnet's short, tapered triangle click. The sink owns this state under its
 * IRQ lock. Mixing uses a separate DMA block and never changes queued music. */
struct ln_pcm_click {uint32_t phase,step,left,total;int32_t gain;};
static inline void ln_pcm_click_clear(volatile struct ln_pcm_click *click){
    *click=(struct ln_pcm_click){0};
}
static inline void ln_pcm_click_request(volatile struct ln_pcm_click *click,uint32_t rate,uint8_t tone,uint8_t volume){
    static const uint16_t hz[]={1650,0,1250,2500};
    static const int16_t gain[]={0,512,1024,2048,4096};
    if(click->left||!rate||tone>3u||tone==1u||!volume||volume>4u)return;
    click->phase=0;click->step=(uint32_t)hz[tone]*65536u/rate;
    click->total=click->left=rate/250u;click->gain=gain[volume];
}
static inline int32_t ln_pcm_click_sample(volatile struct ln_pcm_click *click){
    if(!click->left)return 0;
    uint32_t phase=click->phase&65535u,age=click->total-click->left;
    int32_t triangle=phase<32768u?(int32_t)(phase*2u)-32768:98303-(int32_t)(phase*2u);
    uint32_t ramp=click->left<8u?click->left:8u;if(age<ramp)ramp=age;
    click->phase+=click->step;--click->left;
    return ((triangle*click->gain)/32768)*(int32_t)ramp/8;
}
static inline uint16_t ln_pcm_click_add(int32_t pcm,int32_t click){
    int32_t sum=pcm+click;if(sum>32767)sum=32767;if(sum< -32768)sum=-32768;
    return (uint16_t)(int16_t)sum;
}
static inline bool ln_pcm_click_mix(volatile struct ln_pcm_click *click,uint32_t *out,const uint32_t *pcm,uint32_t frames){
    if(!click->left)return false;
    for(uint32_t i=0;i<frames;++i){
        uint32_t value=pcm?pcm[i]:0;int32_t sample=ln_pcm_click_sample(click);
        out[i]=ln_pcm_click_add((int16_t)value,sample)|
            ((uint32_t)ln_pcm_click_add((int16_t)(value>>16),sample)<<16);
    }
    return true;
}
#endif
