#include "history.h"
#include "services/music/library.h"
#include "services/storage/storage.h"
#include "history_pages.h"
static bool paged;

enum phase { WAIT=0,LOAD_A,LOAD_B,BIND,READY,WRITE,FLUSH,READBACK,ACK,FAILED };
static struct {
    struct ln_music_journal journal;
    uint8_t banks[2][LN_MUSIC_JOURNAL_BANK_BYTES];
    uint32_t staged_version,staged_bank;
    enum phase phase;
    int error;
    bool initialized,stepping,loaded,frozen;
    bool may_read,may_write,playback;
} history;
static bool equal(const uint8_t *a,const uint8_t *b,uint32_t bytes)
{for(uint32_t i=0;i<bytes;i++)if(a[i]!=b[i])return false;return true;}
static void fail(enum ln_music_history_error error)
{history.error=error;history.phase=FAILED;}
static bool capacities(void)
{
    uint32_t a=ln_storage_capacity(LN_STORAGE_MUSIC0),b=ln_storage_capacity(LN_STORAGE_MUSIC1);
    if(!a||!b){fail(LN_HISTORY_MISSING);return false;}
    if(a==LN_HISTORY_PAGED_BANK_BYTES&&b==a){paged=true;return true;}
    if(a!=LN_MUSIC_JOURNAL_BANK_BYTES||b!=LN_MUSIC_JOURNAL_BANK_BYTES){fail(LN_HISTORY_CAPACITY);return false;}
    return true;
}
void ln_music_history_init(void)
{
    if(history.initialized)return;
    history.initialized=true;history.phase=WAIT;
}
void ln_music_history_pin_current(bool present,uint64_t id){if(!history.frozen)ln_paged_history_pin_current(present,id);}
void ln_music_history_freeze(void){history.frozen=true;}
bool ln_music_history_ready(void){return history.initialized&&(paged?ln_paged_history_ready():history.loaded);}
int ln_music_history_error(void){return history.error?history.error:paged?ln_paged_history_error():0;}
bool ln_music_history_busy(void)
{return history.stepping||(paged?ln_paged_history_busy():(history.phase>=LOAD_A&&history.phase<=BIND)||(history.phase>=WRITE&&history.phase<=ACK));}
bool ln_music_history_dirty(void)
{return paged?ln_paged_history_dirty():history.loaded&&ln_music_journal_dirty(&history.journal);}
uint32_t ln_music_history_version(void){return paged?ln_paged_history_version():history.loaded?history.journal.version:0;}
uint32_t ln_music_history_count(void){return paged?UINT32_MAX:history.loaded?history.journal.count:0;}
const struct ln_music_journal_record *ln_music_history_get(uint64_t id)
{return paged?ln_paged_history_get(id):history.loaded?ln_music_journal_get(&history.journal,id):0;}
bool ln_music_history_prefetch(uint64_t id){return !history.frozen&&(paged?ln_paged_history_prefetch(id):history.loaded);}
bool ln_music_history_record_ready(uint64_t id){return paged?ln_paged_history_record_ready(id):history.loaded;}
int ln_music_history_record_error(uint64_t id){return paged?ln_paged_history_record_error(id):history.loaded&&!ln_music_journal_get(&history.journal,id)&&history.journal.count==LN_MUSIC_JOURNAL_CAPACITY?LN_HISTORY_CAPACITY:0;}
static bool writable_events(void){return ln_music_history_ready()&&!ln_music_history_error()&&!history.frozen;}
static bool paged_event(uint64_t id,uint32_t flag,bool present,uint64_t frame){
    if(!writable_events()||!ln_paged_history_record_ready(id))return false;
    const struct ln_music_journal_record *old=ln_paged_history_get(id);
    if(!old&&!present&&flag)return true;
    struct ln_music_journal_record r=old?*old:(struct ln_music_journal_record){.id=id};
    if(!flag){if(r.play_count!=UINT32_MAX)r.play_count++;}
    else{if(present)r.flags|=flag;else r.flags&=~flag;
        if(flag==LN_MUSIC_JOURNAL_BOOKMARK)r.bookmark_frame=present?frame:0;
        if(flag==LN_MUSIC_JOURNAL_RESUME)r.resume_frame=present?frame:0;}
    return ln_paged_history_put(&r);
}
bool ln_music_history_set_favorite(uint64_t id,bool favorite)
{return paged?paged_event(id,1,favorite,0):writable_events()&&ln_music_journal_set_favorite(&history.journal,id,favorite);}
bool ln_music_history_set_bookmark(uint64_t id,bool present,uint64_t frame)
{return paged?paged_event(id,2,present,frame):writable_events()&&ln_music_journal_set_bookmark(&history.journal,id,present,frame);}
bool ln_music_history_set_resume(uint64_t id,bool present,uint64_t frame)
{return paged?paged_event(id,4,present,frame):writable_events()&&ln_music_journal_set_resume(&history.journal,id,present,frame);}
bool ln_music_history_played(uint64_t id)
{return paged?paged_event(id,0,true,0):writable_events()&&ln_music_journal_played(&history.journal,id);}
int ln_music_history_flush(void)
{
    if(paged){int error=ln_music_history_error();return error?error:ln_paged_history_ready()&&!ln_paged_history_busy()&&!ln_paged_history_dirty()?1:0;}
    if(history.error)return history.error;
    if(!history.loaded||history.stepping||history.phase!=READY||ln_music_journal_dirty(&history.journal)||history.journal.staged)return 0;
    uint8_t hash[32];
    if(ln_music_library_identity(hash)&&!equal(hash,history.journal.library_hash,32))return 0;
    return 1;
}
static void step(bool may_read,bool may_write,bool playback)
{
    /* An admitted paged operation owns storage and its buffers until polled
     * complete, even after playback exhausts its background-I/O allowance. */
    if(paged&&ln_paged_history_io_pending()){ln_paged_history_step(may_read,may_write);return;}
    if(!history.initialized||history.error||(!may_read&&!may_write)||ln_storage_busy()||!ln_storage_mounted())return;
    uint8_t hash[32];
    bool have_hash=ln_music_library_identity(hash);
    /* Shutdown may close the library after draining its read owner. A loaded
     * history can still persist its last verified binding; initial load cannot. */
    if(!history.loaded&&!paged&&!have_hash)return;
    if(!capacities())return;
    if(paged){ln_paged_history_step(may_read,may_write);return;}
    /* Legacy whole-bank publication remains synchronous and pause-only. */
    if(playback)return;
    if(!may_write)return;
    switch(history.phase){
    case WAIT:
        history.phase=LOAD_A;return;
    case LOAD_A:
        if(!ln_storage_read(LN_STORAGE_MUSIC0,0,history.banks[0],LN_MUSIC_JOURNAL_BANK_BYTES)){fail(LN_HISTORY_READ_A);return;}
        history.phase=LOAD_B;return;
    case LOAD_B:
        if(!ln_storage_read(LN_STORAGE_MUSIC1,0,history.banks[1],LN_MUSIC_JOURNAL_BANK_BYTES)){fail(LN_HISTORY_READ_B);return;}
        history.phase=BIND;return;
    case BIND:{
        int result=ln_music_journal_load(&history.journal,history.banks[0],LN_MUSIC_JOURNAL_BANK_BYTES,
                                         history.banks[1],LN_MUSIC_JOURNAL_BANK_BYTES);
        if(result<0){fail(result==LN_JOURNAL_CONFLICT?LN_HISTORY_CONFLICT:LN_HISTORY_BOTH_CORRUPT);return;}
        if(!ln_music_journal_rebind(&history.journal,hash)){fail(LN_HISTORY_BIND);return;}
        /* Runtime callbacks throughout both reads saw loaded=false. Publication
         * occurs only after validation/rebinding, so no accepted event is lost. */
        history.loaded=true;history.phase=READY;return;
    }
    case READY:
        if(have_hash&&!equal(history.journal.library_hash,hash,32)&&!ln_music_journal_rebind(&history.journal,hash)){fail(LN_HISTORY_BIND);return;}
        if(!ln_music_journal_dirty(&history.journal))return;
        if(!ln_storage_prepared()){if(ln_storage_prepare_writes()<0)fail(LN_HISTORY_READ_ONLY);return;}
        /* Encode into the inactive bank's RAM buffer. The opposite RAM buffer
         * becomes readback scratch; the active on-disk bank remains untouched. */
        history.staged_bank=history.journal.active_bank==0?1u:0u;
        if(!ln_music_journal_encode_next(&history.journal,history.banks[history.staged_bank],LN_MUSIC_JOURNAL_BANK_BYTES,
                                         &history.staged_version,&history.staged_bank)){fail(LN_HISTORY_ENCODE);return;}
        history.phase=WRITE;return;
    case WRITE:
        if(!ln_storage_prepared()){if(ln_storage_prepare_writes()<0)fail(LN_HISTORY_READ_ONLY);return;}
        if(!ln_storage_write(LN_STORAGE_MUSIC0+history.staged_bank,0,history.banks[history.staged_bank],LN_MUSIC_JOURNAL_BANK_BYTES)){fail(LN_HISTORY_WRITE);return;}
        history.phase=FLUSH;return;
    case FLUSH:
        if(!ln_storage_flush()){fail(LN_HISTORY_FLUSH);return;}
        history.phase=READBACK;return;
    case READBACK:
        if(!ln_storage_read(LN_STORAGE_MUSIC0+history.staged_bank,0,history.banks[history.staged_bank^1u],LN_MUSIC_JOURNAL_BANK_BYTES)){fail(LN_HISTORY_READBACK);return;}
        history.phase=ACK;return;
    case ACK:
        if(!equal(history.banks[0],history.banks[1],LN_MUSIC_JOURNAL_BANK_BYTES)){fail(LN_HISTORY_MISMATCH);return;}
        if(!ln_music_journal_mark_durable(&history.journal,history.staged_version)){fail(LN_HISTORY_ACK);return;}
        history.phase=READY;return;
    default:return;
    }
}
void ln_music_history_step(bool may_write){ln_music_history_service(may_write,may_write,false);}
uint32_t ln_music_history_deadline(uint32_t now)
{
    if(paged)return ln_paged_history_deadline(now,history.may_read,history.may_write);
    uint32_t idle=now+200000u;
    if(!history.initialized||history.error||history.playback||!history.may_write||
       ln_storage_busy()||!ln_storage_mounted())return idle;
    if(!history.loaded){uint8_t hash[32];if(!ln_music_library_identity(hash))return idle;}
    return history.phase!=READY||ln_music_journal_dirty(&history.journal)?now+1000u:idle;
}
void ln_music_history_service(bool may_read,bool may_write,bool playback)
{
    if(history.stepping)return;
    history.may_read=may_read;history.may_write=may_write;history.playback=playback;
    history.stepping=true;step(may_read,may_write,playback);history.stepping=false;
}
