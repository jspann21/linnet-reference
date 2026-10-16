#include <stdint.h>
#include <string.h>
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

struct output { uint8_t *p; uint32_t used,cap; };
static int byte(struct output *o,uint32_t v){if(o->used==o->cap)return 0;o->p[o->used++]=(uint8_t)v;return 1;}
static int copy(struct output *o,const uint8_t *p,uint32_t n){if(n>o->cap-o->used)return 0;memcpy(o->p+o->used,p,n);o->used+=n;return 1;}
static int length(struct output *o,uint32_t n){if(n<15)return 1;n-=15;while(n>=255){if(!byte(o,255))return 0;n-=255;}return byte(o,n);}
EXPORT int32_t ln_ipvf_coalesce(const uint8_t *packed,uint32_t packed_size,const uint8_t *raw,uint32_t raw_size,uint32_t minimum,uint8_t *out,uint32_t capacity){
 if(!packed||!raw||!out||!packed_size||!raw_size||raw_size>262144||packed_size>524288||minimum<4||minimum>262145||capacity>2147483647)return -1;
 uint32_t cursor=0,position=0,anchor=0;struct output o={out,0,capacity};
 while(cursor<packed_size){
  uint32_t token=packed[cursor++],literals=token>>4,match=(token&15)+4;
  if(literals>raw_size-position)return -1;
  if(literals==15){uint32_t ext;do{if(cursor==packed_size)return -1;ext=packed[cursor++];if(ext>raw_size-position-literals)return -1;literals+=ext;}while(ext==255);}
  if(literals>packed_size-cursor||literals>raw_size-position)return -1;
  cursor+=literals;position+=literals;if(cursor==packed_size)break;
  if(packed_size-cursor<2)return -1;uint32_t match_at=cursor,offset=packed[cursor]|((uint32_t)packed[cursor+1]<<8);cursor+=2;if(!offset||offset>position)return -1;
  if(match>raw_size-position)return -1;
  if((token&15)==15){uint32_t ext;do{if(cursor==packed_size)return -1;ext=packed[cursor++];if(ext>raw_size-position-match)return -1;match+=ext;}while(ext==255);}
  if(match>raw_size-position)return -1;
  if(match>=minimum){literals=position-anchor;if(!byte(&o,((literals<15?literals:15)<<4)|(token&15))||!length(&o,literals)||!copy(&o,raw+anchor,literals)||!copy(&o,packed+match_at,cursor-match_at))return -1;anchor=position+match;}
  position+=match;
 }
 if(position!=raw_size)return -1;
 uint32_t literals=position-anchor;if(!byte(&o,(literals<15?literals:15)<<4)||!length(&o,literals)||!copy(&o,raw+anchor,literals))return -1;return (int32_t)o.used;
}


struct score {uint32_t total,count;};
static struct score score(const uint8_t *prev,const uint8_t *cur,int w,int h,int dx,int dy,int step,const struct score *ceiling){
 int x0=dx>0?dx:0,x1=dx<0?w+dx:w,y0=dy>0?dy:0,y1=dy<0?h+dy:h;
 struct score s={0,(uint32_t)(((x1-x0-1)/step+1)*((y1-y0-1)/step+1))};
 for(int y=y0;y<y1;y+=step){
  for(int x=x0;x<x1;x+=step){
   uint32_t a=(uint32_t)(y*w+x)*2,b=(uint32_t)((y-dy)*w+x-dx)*2;
   int lo=(int)cur[a]-prev[b],hi=(int)cur[a+1]-prev[b+1];s.total+=(uint32_t)((lo<0?-lo:lo)+(hi<0?-hi:hi));
  }
  if(ceiling&&(uint64_t)s.total*ceiling->count>(uint64_t)ceiling->total*s.count)break;
 }
 return s;
}
static int consider(const uint8_t *prev,const uint8_t *cur,int w,int h,int dx,int dy,int step,int *bx,int *by,struct score *best){
 struct score s=score(prev,cur,w,h,dx,dy,step,best);uint64_t left=(uint64_t)s.total*best->count,right=(uint64_t)best->total*s.count;
 int distance=(dx<0?-dx:dx)+(dy<0?-dy:dy),old=(*bx<0?-*bx:*bx)+(*by<0?-*by:*by);
 if(left<right||(left==right&&(distance<old||(distance==old&&(dx<*bx||(dx==*bx&&dy<*by)))))){*best=s;*bx=dx;*by=dy;return 1;}return 0;
}
EXPORT int32_t ln_ipvf_estimate_translation(const uint8_t *prev,const uint8_t *cur,uint32_t bytes,uint32_t w,uint32_t h,uint32_t shift,uint32_t step,int32_t state[2]){
 if(!prev||!cur||!state||!w||!h||w>1024||h>1024||w*h>131072||bytes!=w*h*2||shift>32||shift>=w||shift>=h||!step||step>1024)return -1;
 int bx=0,by=0;struct score best=score(prev,cur,(int)w,(int)h,0,0,(int)step,0);
 for(int dy=-(int)shift;dy<=(int)shift;dy+=2)for(int dx=-(int)shift;dx<=(int)shift;dx+=2)consider(prev,cur,(int)w,(int)h,dx,dy,(int)step,&bx,&by,&best);
 int x0=bx-2,x1=bx+2,y0=by-2,y1=by+2;if(x0<-(int)shift)x0=-(int)shift;if(y0<-(int)shift)y0=-(int)shift;if(x1>(int)shift)x1=(int)shift;if(y1>(int)shift)y1=(int)shift;
 for(int dy=y0;dy<=y1;++dy)for(int dx=x0;dx<=x1;++dx)consider(prev,cur,(int)w,(int)h,dx,dy,(int)step,&bx,&by,&best);
 state[0]=bx;state[1]=by;return 0;
}
