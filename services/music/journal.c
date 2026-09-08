#include "journal.h"
static uint32_t read32(const uint8_t *p)
{return p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static uint64_t read64(const uint8_t *p){return read32(p)|((uint64_t)read32(p+4)<<32);}
static void write32(uint8_t *p,uint32_t value)
{p[0]=(uint8_t)value;p[1]=(uint8_t)(value>>8);p[2]=(uint8_t)(value>>16);p[3]=(uint8_t)(value>>24);}
static void write64(uint8_t *p,uint64_t value){write32(p,(uint32_t)value);write32(p+4,(uint32_t)(value>>32));}
static void clear(void *memory,uint32_t bytes){uint8_t *p=memory;for(uint32_t i=0;i<bytes;i++)p[i]=0;}
static bool equal(const uint8_t *a,const uint8_t *b,uint32_t bytes)
{for(uint32_t i=0;i<bytes;i++)if(a[i]!=b[i])return false;return true;}
static uint32_t crc32(const uint8_t *p,uint32_t bytes)
{
    uint32_t crc=UINT32_MAX;
    for(uint32_t i=0;i<bytes;i++){crc^=p[i];for(uint32_t bit=0;bit<8;bit++)crc=(crc>>1)^((0u-(crc&1u))&0xedb88320u);}
    return crc^UINT32_MAX;
}
static bool overlap(const void *a,uint32_t an,const void *b,uint32_t bn)
{
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x<=y?y-x<an:x-y<bn;
}
static bool valid_bank(const uint8_t *b,uint32_t bytes)
{
    if(!b||bytes!=LN_MUSIC_JOURNAL_BANK_BYTES||b[0]!='J'||b[1]!='R'||b[2]!='N'||b[3]!='1'||
       b[4]!=1||b[5]||b[6]!=64||b[7]||read32(b+12)>LN_MUSIC_JOURNAL_CAPACITY||
       crc32(b,4604)!=read32(b+4604))return false;
    for(uint32_t i=52;i<64;i++)if(b[i])return false;
    uint32_t count=read32(b+12);
    for(uint32_t i=0;i<count;i++){
        const uint8_t *record=b+64+i*32;
        uint32_t flags=read32(record+8);
        if(flags&~7u||(!(flags&LN_MUSIC_JOURNAL_BOOKMARK)&&read64(record+16))||
           (!(flags&LN_MUSIC_JOURNAL_RESUME)&&read64(record+24)))return false;
        uint64_t id=read64(record);
        for(uint32_t earlier=0;earlier<i;earlier++)if(read64(b+64+earlier*32)==id)return false;
    }
    for(uint32_t i=64+count*32;i<4604;i++)if(b[i])return false;
    return true;
}
void ln_music_journal_init(struct ln_music_journal *j,const uint8_t hash[32])
{
    if(!j||!hash)return;
    uint8_t copy[32];for(uint32_t i=0;i<32;i++)copy[i]=hash[i];
    clear(j,sizeof(*j));for(uint32_t i=0;i<32;i++)j->library_hash[i]=copy[i];
    j->ready=true;j->active_bank=LN_MUSIC_JOURNAL_NO_BANK;j->staged_bank=LN_MUSIC_JOURNAL_NO_BANK;
}
int ln_music_journal_load(struct ln_music_journal *j,const uint8_t *a,uint32_t an,const uint8_t *b,uint32_t bn)
{
    if(!j||(a&&overlap(j,sizeof(*j),a,an))||(b&&overlap(j,sizeof(*j),b,bn)))return LN_JOURNAL_ARGUMENT;
    bool av=valid_bank(a,an),bv=valid_bank(b,bn);
    if(!av&&!bv)return LN_JOURNAL_BOTH_INVALID;
    uint32_t bank=av?0u:1u;
    if(av&&bv){
        uint32_t as=read32(a+8),bs=read32(b+8),delta=as-bs;
        if(!delta){if(!equal(a,b,LN_MUSIC_JOURNAL_BANK_BYTES))return LN_JOURNAL_CONFLICT;}
        else if(delta==0x80000000u)return LN_JOURNAL_CONFLICT;
        else bank=delta<0x80000000u?0u:1u;
    }
    const uint8_t *chosen=bank?b:a;
    /* Validation completed; no fallible operation remains after state changes. */
    clear(j,sizeof(*j));j->ready=j->has_durable=true;j->active_bank=bank;j->staged_bank=LN_MUSIC_JOURNAL_NO_BANK;
    j->sequence=read32(chosen+8);j->version=j->durable_version=read32(chosen+48);j->count=read32(chosen+12);
    for(uint32_t i=0;i<32;i++)j->library_hash[i]=chosen[16+i];
    for(uint32_t i=0;i<j->count;i++){
        const uint8_t *record=chosen+64+i*32;struct ln_music_journal_record *r=&j->records[i];
        r->id=read64(record);r->flags=read32(record+8);r->play_count=read32(record+12);
        r->bookmark_frame=read64(record+16);r->resume_frame=read64(record+24);
    }
    return j->count?LN_JOURNAL_VALID:LN_JOURNAL_VALID_EMPTY;
}
bool ln_music_journal_dirty(const struct ln_music_journal *j)
{return j&&j->ready&&(!j->has_durable||j->version!=j->durable_version);}
const struct ln_music_journal_record *ln_music_journal_get(const struct ln_music_journal *j,uint64_t id)
{
    if(!j||!j->ready||j->count>LN_MUSIC_JOURNAL_CAPACITY)return 0;
    for(uint32_t i=0;i<j->count;i++)if(j->records[i].id==id)return &j->records[i];
    return 0;
}
static struct ln_music_journal_record *record(struct ln_music_journal *j,uint64_t id,bool create)
{
    if(!j||!j->ready||j->count>LN_MUSIC_JOURNAL_CAPACITY)return 0;
    for(uint32_t i=0;i<j->count;i++)if(j->records[i].id==id)return &j->records[i];
    if(!create||j->count==LN_MUSIC_JOURNAL_CAPACITY)return 0;
    struct ln_music_journal_record *r=&j->records[j->count++];clear(r,sizeof(*r));r->id=id;return r;
}
bool ln_music_journal_set_favorite(struct ln_music_journal *j,uint64_t id,bool favorite)
{
    if(!j||!j->ready)return false;
    struct ln_music_journal_record *r=record(j,id,favorite);
    if(!r)return !favorite;
    uint32_t flags=favorite?r->flags|LN_MUSIC_JOURNAL_FAVORITE:r->flags&~LN_MUSIC_JOURNAL_FAVORITE;
    if(flags!=r->flags){r->flags=flags;j->version++;}return true;
}
static bool position(struct ln_music_journal *j,uint64_t id,bool present,uint64_t frame,bool bookmark)
{
    if(!j||!j->ready)return false;
    struct ln_music_journal_record *r=record(j,id,present);
    if(!r)return !present;
    uint32_t mask=bookmark?LN_MUSIC_JOURNAL_BOOKMARK:LN_MUSIC_JOURNAL_RESUME;
    uint32_t flags=present?r->flags|mask:r->flags&~mask;
    uint64_t value=present?frame:0;
    uint64_t *target=bookmark?&r->bookmark_frame:&r->resume_frame;
    if(r->flags!=flags||*target!=value){r->flags=flags;*target=value;j->version++;}return true;
}
bool ln_music_journal_set_bookmark(struct ln_music_journal *j,uint64_t id,bool present,uint64_t frame)
{return position(j,id,present,frame,true);}
bool ln_music_journal_set_resume(struct ln_music_journal *j,uint64_t id,bool present,uint64_t frame)
{return position(j,id,present,frame,false);}
bool ln_music_journal_played(struct ln_music_journal *j,uint64_t id)
{
    struct ln_music_journal_record *r=record(j,id,true);if(!r)return false;
    if(r->play_count!=UINT32_MAX){r->play_count++;j->version++;}return true;
}
bool ln_music_journal_rebind(struct ln_music_journal *j,const uint8_t hash[32])
{
    if(!j||!j->ready||!hash)return false;
    if(!equal(j->library_hash,hash,32)){for(uint32_t i=0;i<32;i++)j->library_hash[i]=hash[i];j->version++;}
    return true;
}
bool ln_music_journal_encode_next(struct ln_music_journal *j,uint8_t *out,uint32_t bytes,uint32_t *version,uint32_t *bank)
{
    if(!j||!ln_music_journal_dirty(j)||!out||!version||!bank||bytes!=LN_MUSIC_JOURNAL_BANK_BYTES||j->staged||j->count>128||
       overlap(j,sizeof(*j),out,bytes)||overlap(j,sizeof(*j),version,4)||overlap(j,sizeof(*j),bank,4)||
       overlap(out,bytes,version,4)||overlap(out,bytes,bank,4)||overlap(version,4,bank,4))return false;
    clear(out,bytes);out[0]='J';out[1]='R';out[2]='N';out[3]='1';out[4]=1;out[6]=64;
    write32(out+8,j->sequence+1u);write32(out+12,j->count);write32(out+48,j->version);
    for(uint32_t i=0;i<32;i++)out[16+i]=j->library_hash[i];
    for(uint32_t i=0;i<j->count;i++){
        const struct ln_music_journal_record *r=&j->records[i];uint8_t *p=out+64+i*32;
        write64(p,r->id);write32(p+8,r->flags);write32(p+12,r->play_count);write64(p+16,r->bookmark_frame);write64(p+24,r->resume_frame);
    }
    write32(out+4604,crc32(out,4604));
    j->staged=true;j->staged_sequence=j->sequence+1u;j->staged_version=j->version;
    j->staged_bank=j->active_bank==0?1u:0u;*version=j->staged_version;*bank=j->staged_bank;return true;
}
bool ln_music_journal_mark_durable(struct ln_music_journal *j,uint32_t version)
{
    if(!j||!j->ready||!j->staged||version!=j->staged_version)return false;
    j->sequence=j->staged_sequence;j->durable_version=j->staged_version;j->active_bank=j->staged_bank;
    j->staged=false;j->has_durable=true;j->staged_bank=LN_MUSIC_JOURNAL_NO_BANK;return true;
}
bool ln_music_journal_discard_unsubmitted(struct ln_music_journal *j,uint32_t version)
{
    if(!j||!j->ready||!j->staged||version!=j->staged_version)return false;
    j->staged=false;j->staged_bank=LN_MUSIC_JOURNAL_NO_BANK;return true;
}
