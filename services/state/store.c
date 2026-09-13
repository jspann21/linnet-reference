#include "services/state/store.h"
#include "boot/include/linnet_boot.h"
#if !defined(LINNET_PROFILE_RELEASE)
__attribute__((weak)) void ln_state_publication_step(uint32_t stage){(void)stage;}
#define PUBLICATION_STEP(stage) ln_state_publication_step(stage)
#else
#define PUBLICATION_STEP(stage) ((void)0)
#endif
static uint32_t get32(const uint8_t *p){return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put32(uint8_t *p,uint32_t n){for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(n>>(8*i));}
static int same(const uint8_t*a,const uint8_t*b,uint32_t n){for(uint32_t i=0;i<n;++i)if(a[i]!=b[i])return 0;return 1;}
static int blank(const uint8_t*p,uint32_t n){for(uint32_t i=0;i<n;++i)if(p[i])return 0;return 1;}
int ln_state_encode(uint8_t r[512],uint32_t generation,const uint8_t *payload,uint32_t n){
    if(!r||!generation||n>480||(!payload&&n))return 0;
    for(unsigned i=0;i<512;++i)r[i]=0;
    put32(r,0x54415453u);put32(r+4,0);put32(r+8,generation);put32(r+12,n);
    for(uint32_t i=0;i<n;++i)r[28+i]=payload[i];
    put32(r+508,ln_crc32(r,508));return 1;
}
int ln_state_decode(const uint8_t r[512],uint32_t *generation,uint32_t *length){
    if(!r||!generation||!length||get32(r)!=0x54415453u||get32(r+4)||!get32(r+8)||
       get32(r+12)>480||!blank(r+16,12)||ln_crc32(r,508)!=get32(r+508))return 0;
    uint32_t n=get32(r+12);if(!blank(r+28+n,480-n))return 0;
    *generation=get32(r+8);*length=n;return 1;
}
int ln_state_open(struct ln_state_store*s,const struct ln_state_io*io){
    if(!s||!io||!io->read||!io->write||!io->flush)return -1;
    s->ready=0;s->poisoned=1;s->io=*io;s->generation=s->length=0;s->active=1;
    uint8_t r[2][512];uint32_t generation[2]={0},length[2]={0};
    if(io->read(io->context,0,r[0])!=1||io->read(io->context,1,r[1])!=1)return -1;
    int a=ln_state_decode(r[0],&generation[0],&length[0]);
    int b=ln_state_decode(r[1],&generation[1],&length[1]);
    if(!a&&!b){if(!blank(r[0],512)||!blank(r[1],512))return -1;s->ready=1;s->poisoned=0;return 0;}
    if(a&&b&&generation[0]==generation[1]&&!same(r[0],r[1],512))return -1;
    uint32_t pick=b&&(!a||generation[1]>generation[0])?1u:0u;
    s->generation=generation[pick];s->length=length[pick];s->active=pick;
    for(uint32_t i=0;i<s->length;++i)s->payload[i]=r[pick][28+i];
    s->ready=1;s->poisoned=0;return 1;
}
int ln_state_publish(struct ln_state_store*s,const uint8_t*payload,uint32_t n){
    if(!s||!s->ready||s->poisoned||s->generation==UINT32_MAX||n>480||(!payload&&n))return 0;
    uint8_t record[512],check[512];uint32_t next=s->generation+1,copy=s->active^1u;
    if(!ln_state_encode(record,next,payload,n))return 0;
    s->poisoned=1;
    PUBLICATION_STEP(1);
    if(s->io.write(s->io.context,copy,record)!=1)return 0;
    PUBLICATION_STEP(2);
    if(s->io.flush(s->io.context)!=1)return 0;
    PUBLICATION_STEP(3);
    if(s->io.read(s->io.context,copy,check)!=1||!same(record,check,512))return 0;
    PUBLICATION_STEP(4);
    s->generation=next;s->active=copy;s->length=n;
    for(uint32_t i=0;i<n;++i)s->payload[i]=record[28+i];
    s->poisoned=0;return 1;
}
