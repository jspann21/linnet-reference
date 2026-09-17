#include "collections.h"
#include "services/storage/storage.h"
#include "boot/include/linnet_bytes.h"
#include "boot/include/linnet_boot.h"
/* Independent dual banks. Body first, header last; CRC covers the complete
 * snapshot. The previous bank remains intact until readback verifies its peer. */
#define BODY 512u
#define LISTS (BODY+4u+LN_COLLECTION_RESUME)
#define ENTRY (40u+8u*LINNET_QUEUE_CAPACITY)
static uint8_t saved[LN_COLLECTION_BYTES],io[LN_COLLECTION_BYTES];
static uint32_t bank,generation,revision,durable,snapshot,phase,offset,ticket,loading;
static bool ready,pending,failed,available,stepping;
static struct ln_collection entry;
static uint32_t crc(uint8_t *p){uint32_t old=ln_read_le32(p+12);ln_write_le32(p+12,0);uint32_t value=ln_crc32(p,LN_COLLECTION_BYTES);ln_write_le32(p+12,old);return value;}
static bool valid(uint8_t *p){
    if(ln_read_le32(p)!=0x54534c4cu||ln_read_le32(p+4)!=1||!ln_read_le32(p+8)||ln_read_le32(p+12)!=crc(p)||ln_read_le32(p+BODY)>LN_COLLECTION_RESUME)return false;
    for(uint32_t n=0;n<LN_COLLECTION_SLOTS;n++){uint8_t *e=p+LISTS+n*ENTRY;
        if(e[31]||ln_read_le32(e+32)>LINNET_QUEUE_CAPACITY||(!e[0]&&ln_read_le32(e+32)))return false;}
    return true;
}
bool ln_collections_ready(void){return ready;}
bool ln_collections_writable(void){return ready&&available&&!failed;}
bool ln_collections_busy(void){return pending||phase!=0;}
bool ln_collections_dirty(void){return revision!=durable;}
uint32_t ln_collections_revision(void){return revision+durable+(ready?1u:0u)+(failed?1u:0u);}
const char *ln_collections_status(void){return !ready?"Loading playlists...":!available?"Sync to enable saving":failed?"Save failed; reconnect USB":revision!=durable?"Saving...":"Saved";}
const struct ln_collection *ln_collection_get(uint32_t slot){
    if(!ready||slot>=LN_COLLECTION_SLOTS)return 0;const uint8_t *p=saved+LISTS+slot*ENTRY;
    for(uint32_t i=0;i<32;i++)entry.name[i]=(char)p[i];entry.count=ln_read_le32(p+32);
    for(uint32_t i=0;i<entry.count;i++)entry.ids[i]=ln_read_le64(p+40+8*i);return &entry;
}
int ln_collection_free(void){if(!ready)return -1;for(uint32_t i=0;i<LN_COLLECTION_SLOTS;i++)if(!saved[LISTS+i*ENTRY])return (int)i;return -1;}
bool ln_collection_put(uint32_t slot,const struct ln_collection *value){
    if(!ready||!available||failed||slot>=LN_COLLECTION_SLOTS||!value||value->name[31]||value->count>LINNET_QUEUE_CAPACITY||(!value->name[0]&&value->count))return false;
    uint8_t *p=saved+LISTS+slot*ENTRY;for(uint32_t i=0;i<ENTRY;i++)p[i]=0;
    for(uint32_t i=0;i<32;i++)p[i]=(uint8_t)value->name[i];ln_write_le32(p+32,value->count);
    for(uint32_t i=0;i<value->count;i++)ln_write_le64(p+40+8*i,value->ids[i]);++revision;return true;
}
bool ln_collections_resume_set(const uint8_t *p,uint32_t n){
    if(!ready||!available||failed||n>LN_COLLECTION_RESUME)return false;
    bool changed=ln_read_le32(saved+BODY)!=n;for(uint32_t i=0;i<n;i++)if(saved[BODY+4+i]!=p[i])changed=true;
    if(changed){ln_write_le32(saved+BODY,n);for(uint32_t i=0;i<n;i++)saved[BODY+4+i]=p[i];++revision;}return true;
}
uint32_t ln_collections_resume_get(uint8_t *p,uint32_t cap){uint32_t n=ln_read_le32(saved+BODY);if(!ready||n>cap)return 0;for(uint32_t i=0;i<n;i++)p[i]=saved[BODY+4+i];return n;}
static void step(bool read,bool write){
    if(failed)return;
    if(!ready&&!phase){
        if(!read||!ln_storage_startup_complete())return;
        available=ln_storage_capacity(LN_STORAGE_LIST0)==LN_COLLECTION_BYTES&&ln_storage_capacity(LN_STORAGE_LIST1)==LN_COLLECTION_BYTES;
        if(!available){ready=true;return;}phase=1;loading=offset=0;
    }
    if(!phase){
        if(!write||revision==durable)return;
        int proof=ln_storage_prepare_writes();if(!proof)return;if(proof<0){failed=true;return;}
        for(uint32_t i=0;i<LN_COLLECTION_BYTES;i++)io[i]=saved[i];
        ln_write_le32(io,0x54534c4cu);ln_write_le32(io+4,1);ln_write_le32(io+8,generation+1u);ln_write_le32(io+12,crc(io));
        if(generation==UINT32_MAX){failed=true;return;}snapshot=revision;offset=BODY;phase=2;
    }
    uint32_t size=phase==3?BODY:4096u;
    if(size>LN_COLLECTION_BYTES-offset)size=LN_COLLECTION_BYTES-offset;
    if(pending){uint32_t transferred=0;int result=ln_storage_async_poll_deferred(ticket,&transferred);if(!result)return;pending=false;
        if(result!=1||transferred!=size){failed=true;return;}
        offset+=size;
        if(phase==1&&offset==LN_COLLECTION_BYTES){
            if(valid(io)){uint32_t seq=ln_read_le32(io+8);
                if(seq==generation&&generation){for(uint32_t i=0;i<LN_COLLECTION_BYTES;i++)if(saved[i]!=io[i]){failed=true;return;}}
                if(seq>generation){for(uint32_t i=0;i<LN_COLLECTION_BYTES;i++)saved[i]=io[i];generation=seq;bank=loading;}}
            if(!loading){loading=1;offset=0;}else{ready=true;phase=0;if(!generation)failed=true;}
        }else if(phase==2&&offset==LN_COLLECTION_BYTES){phase=3;offset=0;}
        else if(phase==3){phase=4;offset=0;}
        else if(phase==4&&offset==LN_COLLECTION_BYTES){
            if(!valid(io)||ln_read_le32(io+8)!=generation+1u){failed=true;return;}
            generation++;bank^=1u;durable=snapshot;phase=0;
        }
        return;
    }
    if((phase==1&&!read)||(phase!=1&&!write))return;
    int result=phase==1||phase==4?ln_storage_async_read(LN_STORAGE_LIST0+(phase==1?loading:bank^1u),offset,io+offset,size,&ticket):
        ln_storage_async_write(LN_STORAGE_LIST0+(bank^1u),offset,io+offset,size,&ticket);
    if(result<0)failed=true;else pending=result==1;
}
void ln_collections_step(bool read,bool write){if(stepping)return;stepping=true;step(read,write);stepping=false;}
