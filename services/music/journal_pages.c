#include "journal_pages.h"
static uint32_t get(const uint8_t *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static uint64_t get64(const uint8_t *p){return get(p)|((uint64_t)get(p+4)<<32);}
static void put(uint8_t *p,uint32_t x){for(uint32_t i=0;i<4;i++)p[i]=(uint8_t)(x>>(8*i));}
static void put64(uint8_t *p,uint64_t x){put(p,(uint32_t)x);put(p+4,(uint32_t)(x>>32));}
static bool same(const uint8_t *a,const uint8_t *b,uint32_t n){for(uint32_t i=0;i<n;i++)if(a[i]!=b[i])return false;return true;}
static bool zero(const uint8_t *p,uint32_t n){for(uint32_t i=0;i<n;i++)if(p[i])return false;return true;}
static uint32_t crc(const uint8_t *p){uint32_t x=UINT32_MAX;for(uint32_t i=0;i<4092;i++){x^=p[i];for(uint32_t k=0;k<8;k++)x=(x>>1)^((0u-(x&1u))&0xedb88320u);}return ~x;}
bool ln_history_superblock(const uint8_t *p,uint8_t epoch[16]){
    if(!p||!epoch||get(p)!=0x0032484au||get(p+4)!=0x00400002u||get(p+8)!=LN_HISTORY_PAGED_BANK_BYTES||
       get(p+12)!=1024||get(p+16)!=125||get(p+20)!=32||!zero(p+40,4052)||get(p+4092)!=crc(p))return false;
    for(uint32_t i=0;i<16;i++)epoch[i]=p[24+i];return true;
}
uint32_t ln_history_page_hash(uint64_t id){uint32_t x=(uint32_t)id^(uint32_t)(id>>32);x^=x>>16;x*=0x7feb352du;x^=x>>15;x*=0x846ca68bu;x^=x>>16;return x&1023u;}
static bool valid_record(const struct ln_music_journal_record *r){return r&&!(r->flags&~7u)&&((r->flags&2u)||!r->bookmark_frame)&&((r->flags&4u)||!r->resume_frame);}
static void record(const uint8_t *p,struct ln_music_journal_record *r){r->id=get64(p);r->flags=get(p+8);r->play_count=get(p+12);r->bookmark_frame=get64(p+16);r->resume_frame=get64(p+24);}
static bool valid(const uint8_t *p,uint32_t index,const uint8_t epoch[16]){
    if(!p||get(p)!=0x0032504au||get(p+4)!=0x00400002u||get(p+8)!=index||get(p+16)>125||
       !same(p+40,epoch,16)||!zero(p+56,8)||get(p+4092)!=crc(p))return false;
    uint32_t n=get(p+16);
    for(uint32_t i=0;i<128;i++)if(((p[24+i/8]>>(i&7))&1u)!=(i<n))return false;
    for(uint32_t i=0;i<n;i++){struct ln_music_journal_record r;record(p+64+i*32,&r);if(!valid_record(&r))return false;
        for(uint32_t j=0;j<i;j++)if(get64(p+64+j*32)==r.id)return false;}
    return zero(p+64+n*32,4092-64-n*32);
}
int ln_history_page_load(struct ln_history_page *s,const uint8_t *a,const uint8_t *b,uint32_t index,const uint8_t epoch[16]){
    if(!s||!epoch||index>=1024)return -3;bool av=valid(a,index,epoch),bv=valid(b,index,epoch);if(!av&&!bv)return -1;
    uint32_t bank=av?0u:1u;if(av&&bv){uint32_t d=get(b+12)-get(a+12);if(d==0x80000000u||(!d&&!same(a,b,4096)))return -2;if(d&&d<0x80000000u)bank=1;}
    const uint8_t *p=bank?b:a;s->index=index;s->count=get(p+16);s->sequence=get(p+12);s->version=s->durable_version=get(p+20);s->bank=bank;
    for(uint32_t i=0;i<16;i++)s->epoch[i]=epoch[i];for(uint32_t i=0;i<s->count;i++)record(p+64+i*32,&s->records[i]);s->ready=true;s->staged=false;return 1;
}
const struct ln_music_journal_record *ln_history_page_get(const struct ln_history_page *s,uint64_t id){if(!s||!s->ready)return 0;for(uint32_t i=0;i<s->count;i++)if(s->records[i].id==id)return &s->records[i];return 0;}
bool ln_history_page_put(struct ln_history_page *s,const struct ln_music_journal_record *r){
    if(!s||!s->ready||!valid_record(r))return false;uint32_t i=0;while(i<s->count&&s->records[i].id!=r->id)i++;
    if(i==125)return false;
    if(i<s->count){const struct ln_music_journal_record *a=&s->records[i];if(a->flags==r->flags&&a->play_count==r->play_count&&a->bookmark_frame==r->bookmark_frame&&a->resume_frame==r->resume_frame)return true;}
    else s->count++;s->records[i]=*r;s->version++;return true;
}
bool ln_history_page_encode(struct ln_history_page *s,uint8_t out[4096]){
    if(!s||!out||!s->ready||s->staged||s->version==s->durable_version)return false;
    for(uint32_t i=0;i<4096;i++)out[i]=0;put(out,0x0032504au);put(out+4,0x00400002u);put(out+8,s->index);put(out+12,s->sequence+1);put(out+16,s->count);put(out+20,s->version);
    for(uint32_t i=0;i<16;i++)out[40+i]=s->epoch[i];for(uint32_t i=0;i<s->count;i++){out[24+i/8]|=(uint8_t)(1u<<(i&7));const struct ln_music_journal_record *r=&s->records[i];uint8_t *p=out+64+i*32;put64(p,r->id);put(p+8,r->flags);put(p+12,r->play_count);put64(p+16,r->bookmark_frame);put64(p+24,r->resume_frame);}
    put(out+4092,crc(out));s->staged=true;s->staged_version=s->version;s->staged_sequence=s->sequence+1;s->staged_bank=s->bank^1u;return true;
}
bool ln_history_page_ack(struct ln_history_page *s){if(!s||!s->staged)return false;s->bank=s->staged_bank;s->sequence=s->staged_sequence;s->durable_version=s->staged_version;s->staged=false;return true;}
