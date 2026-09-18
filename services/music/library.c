#include "library.h"
#include "queue.h"
#include "services/storage/storage.h"
#include "hal/api/platform.h"
#include "boot/include/linnet_bytes.h"

enum job { JOB_NONE=0,JOB_WINDOW,JOB_SELECTION,JOB_SEARCH,JOB_GROUP,JOB_MEMBER,JOB_PREFETCH,JOB_QUEUE,JOB_VIEW,JOB_VIEW_GROUP,JOB_GROUP_RECORD,JOB_TRACK_RECORD,JOB_TRACK_IDS };
struct library {
    struct ln_music_db db;
    /* Bounded shared page cache: titles, group/member tables and search indexes.
     * Tags publish only after a complete read; reload clears the entire cache. */
    uint8_t pages[32][4096];
    uint32_t page_tags[32],page_used[32],page_clock;
    bool page_valid[32];
    struct ln_fat32_file file;
    struct ln_music_library_row rows[LN_MUSIC_LIBRARY_ROWS],scratch,selection,prefetch;
    struct ln_music_group group;
    union {char prefix[256];struct ln_music_track record;};
    union {char group_name[256];uint64_t ids[LN_MUSIC_ID_BATCH];};
    uint32_t generation,revision,first,job_index,selection_index,selection_token,job_token;
    uint32_t query_index,query_ordinal,query_result,io_offset,io_size;
    uint8_t *io_buffer;
    bool valid[LN_MUSIC_LIBRARY_ROWS],io_active,paused,reopen;
    bool selection_pending,selection_ready,query_pending,query_ready;
    bool prefetch_pending,prefetch_ready;
    uint32_t prefetch_index,prefetch_token;
    uint32_t queue_group,queue_ordinal,queue_token,queue_result,queue_done_token,queue_job_group,queue_job_ordinal,queue_job_token;
    bool queue_pending,queue_ready;
    enum ln_music_library_status status;
    enum job job,query;
    uint8_t stage;
    int error;
};
static struct library library;
static bool window_enabled=true;
static uint32_t generation=0x10000000u;
static void clear(void *memory,uint32_t count){
#if defined(__arm__)
    extern void ln_memory_clear(void *,uint32_t);ln_memory_clear(memory,count);
#else
    uint8_t *p=memory;for(uint32_t i=0;i<count;i++)p[i]=0;
#endif
}
static void text_copy(char out[256],const char *in){uint32_t i=0;while(i<255&&in[i]){out[i]=in[i];i++;}out[i]=0;}
static uint32_t next_generation(void){if(++generation>=0x20000000u)generation=0x10000000u;return generation;}
static void changed(void){library.revision++;}
static void fail(int error)
{
    library.error=error;library.job=JOB_NONE;library.reopen=false;
    library.status=library.io_active?LN_LIBRARY_DRAINING:LN_LIBRARY_ERROR;
    if(library.io_active)ln_storage_media_cancel(library.generation);
    changed();
}
static bool ready(void){return library.status==LN_LIBRARY_READY;}
static bool superseded_job(void){
    return (library.job==JOB_WINDOW&&!window_enabled)||
        (library.job==JOB_SELECTION&&library.job_token!=library.selection_token)||
        (library.job==JOB_PREFETCH&&library.job_token!=library.prefetch_token)||
        (library.job==JOB_QUEUE&&library.queue_job_token!=library.queue_token);
}
static bool retire_superseded_job(void){
    if(!superseded_job())return false;
    /* The DB scratch buffer still belongs to an admitted storage request.
     * Retire that owner before abandoning its parser operation; the newest
     * selection/prefetch/resolver intent remains pending. */
    if(library.io_active){
        ln_storage_media_cancel(library.generation);
        if(!ln_storage_media_poll(library.generation,0,0))return true;
        library.io_active=false;library.io_buffer=0;
        library.generation=next_generation();
    }
    library.db.busy=library.db.pending=false;
    library.job=JOB_NONE;library.stage=0;
    return true;
}
uint32_t ln_music_library_deadline(uint32_t now){
    if(library.io_active)return now;
    if(library.paused)return now+200000u;
    if(library.status==LN_LIBRARY_OPENING||library.status==LN_LIBRARY_VERIFYING||
       library.status==LN_LIBRARY_DRAINING)return now;
    if(!ready())return now+200000u;
    if(library.job!=JOB_NONE||library.selection_pending||library.selection_ready||
       library.prefetch_pending||library.prefetch_ready||library.queue_pending||library.queue_ready||library.query_pending||library.query_ready)return now;
    for(uint32_t i=0;window_enabled&&i<LN_MUSIC_LIBRARY_ROWS&&library.first+i<library.db.tracks;++i)
        if(!library.valid[i])return now;
    return now+200000u;
}
static void start(void)
{
    uint32_t revision=library.revision+1u;
    bool paused=library.paused;
    clear(&library,sizeof(library));library.status=LN_LIBRARY_OPENING;
    library.revision=revision;library.paused=paused;library.generation=next_generation();
}
void ln_music_library_init(void){start();}
static int read_database_raw(void *context,uint64_t offset,uint8_t *buffer,uint32_t bytes)
{
    (void)context;
    if(offset>UINT32_MAX||!bytes||bytes>4096u)return LN_DB_ARGUMENT;
    if(library.io_active){
        if(library.io_offset!=(uint32_t)offset||library.io_size!=bytes||library.io_buffer!=buffer)return LN_DB_ARGUMENT;
        uint32_t transferred=0;
        int result=0;
        /* A metadata page is at most 4 KiB. Group ready FAT/cache transitions
         * without recursive runtime work between each sector; yield as soon
         * as hardware really waits. Cancellation retains its ordinary drain. */
        for(uint32_t step=0;step<4u;++step){
            result=ln_storage_media_poll_deferred(library.generation,0,&transferred);
            if(result)break;
            uint32_t now=ln_time_us(),deadline;
            if(ln_storage_idle_wait(now,&deadline)&&(int32_t)(deadline-now)>0)break;
        }
        if(!result)return 0;
        library.io_active=false;library.io_buffer=0;
        library.generation=next_generation();
        return result==1&&transferred==bytes?1:LN_DB_IO;
    }
    if(library.paused)return 0;
    int result=ln_storage_media_read(&library.file,(uint32_t)offset,buffer,bytes,library.generation);
    if(result!=1)return result;
    library.io_active=true;library.io_offset=(uint32_t)offset;library.io_size=bytes;library.io_buffer=buffer;
    return 0;
}
static int read_database(void *context,uint64_t offset,uint8_t *buffer,uint32_t bytes)
{
    if(!ready())return read_database_raw(context,offset,buffer,bytes);
    if(offset>library.file.size||!bytes||bytes>4096u||bytes>library.file.size-offset)return LN_DB_ARGUMENT;
    uint32_t copied=0;
    while(copied<bytes){
        uint32_t address=(uint32_t)offset+copied,page=address/4096u,slot=32u;
        /* Fully associative replacement keeps record and string pages together,
         * even when their file offsets differ by a multiple of cache capacity. */
        for(uint32_t i=0;i<32u;i++)
            if(library.page_valid[i]&&library.page_tags[i]==page){slot=i;break;}
        if(slot==32u){
            if(library.io_active){
                for(uint32_t i=0;i<32u;i++)if(library.io_buffer==library.pages[i]){slot=i;break;}
                if(slot==32u)return LN_DB_ARGUMENT;
            }else{
                slot=0;
                for(uint32_t i=0;i<32u;i++){
                    if(!library.page_valid[i]){slot=i;break;}
                    if((uint32_t)(library.page_clock-library.page_used[i])>
                       (uint32_t)(library.page_clock-library.page_used[slot]))slot=i;
                }
            }
        }
        uint32_t base=page*4096u,size=library.file.size-base;
        if(size>4096u)size=4096u;
        if(!library.page_valid[slot]||library.page_tags[slot]!=page){
            library.page_valid[slot]=false;
            int result=read_database_raw(context,base,library.pages[slot],size);
            if(result!=1)return result;
            library.page_tags[slot]=page;library.page_valid[slot]=true;
        }
        library.page_used[slot]=++library.page_clock;
        uint32_t within=address-base,count=size-within;
        if(count>bytes-copied)count=bytes-copied;
        for(uint32_t i=0;i<count;i++)buffer[copied+i]=library.pages[slot][within+i];
        copied+=count;
    }
    return 1;
}
static void stop(bool reopen)
{
    library.reopen=reopen;library.status=LN_LIBRARY_DRAINING;
    library.error=0;
    library.selection_ready=library.query_ready=false;
    library.prefetch_ready=library.prefetch_pending=false;library.queue_pending=library.queue_ready=false;
    if(library.io_active)ln_storage_media_cancel(library.generation);
    changed();
}
void ln_music_library_reload(void){stop(true);}
void ln_music_library_cancel(void){stop(false);}
void ln_music_library_pause(bool pause){library.paused=pause;}
enum ln_music_library_status ln_music_library_status(void){return library.status;}
int ln_music_library_error(void){return library.error;}
uint32_t ln_music_library_count(void){return ready()?library.db.tracks:0;}
uint32_t ln_music_library_group_count(void){return ready()?library.db.groups:0;}
uint32_t ln_music_library_revision(void){return library.revision;}
uint32_t ln_music_library_verified_bytes(void){return library.db.cursor;}
bool ln_music_library_identity(uint8_t out[32])
{
    if(!out||!ready()||!library.db.verified)return false;
    for(uint32_t i=0;i<32;i++)out[i]=library.db.expected_hash[i];
    return true;
}
void ln_music_library_window_enable(bool enabled){window_enabled=enabled;}
void ln_music_library_window(uint32_t first)
{
    if(library.first==first)return;
    library.first=first;
    for(uint32_t i=0;i<LN_MUSIC_LIBRARY_ROWS;i++)library.valid[i]=false;
    changed();
}
const struct ln_music_library_row *ln_music_library_row(uint32_t index)
{
    if(!ready()||index<library.first||index-library.first>=LN_MUSIC_LIBRARY_ROWS)return 0;
    uint32_t slot=index-library.first;
    return library.valid[slot]?&library.rows[slot]:0;
}
bool ln_music_library_select(uint32_t index)
{
    if(!ready()||index>=library.db.tracks)return false;
    library.selection_index=index;library.selection_token++;
    library.selection_ready=false;library.selection_pending=true;return true;
}
bool ln_music_library_take_selection(struct ln_music_library_row *out)
{
    if(!out||!ready()||!library.selection_ready)return false;
    *out=library.selection;library.selection_ready=false;return true;
}
bool ln_music_library_prefetch(uint32_t index){
    if(!ready()||index>=library.db.tracks)return false;
    library.prefetch_index=index;++library.prefetch_token;
    library.prefetch_ready=false;library.prefetch_pending=true;return true;
}
bool ln_music_library_take_prefetch(struct ln_music_library_row *out){
    if(!out||!ready()||!library.prefetch_ready)return false;
    *out=library.prefetch;library.prefetch_ready=false;return true;
}
void ln_music_library_cancel_prefetch(void){
    ++library.prefetch_token;library.prefetch_pending=library.prefetch_ready=false;
}
bool ln_music_library_queue_member(uint32_t group,uint32_t ordinal,uint32_t token){
    group&=~LN_QUEUE_REVERSE;
    if(!ready()||!token||group>=library.db.groups)return false;
    library.queue_group=group;library.queue_ordinal=ordinal;library.queue_token=token;
    library.queue_pending=true;library.queue_ready=false;return true;
}
bool ln_music_library_take_queue_member(uint32_t *track,uint32_t *token){
    if(!ready()||!track||!token||!library.queue_ready)return false;
    *track=library.queue_result;*token=library.queue_done_token;library.queue_ready=false;return true;
}
static void queue_complete(uint32_t track){
    if(library.queue_job_token==library.queue_token){library.queue_result=track;
        library.queue_done_token=library.queue_job_token;library.queue_pending=false;library.queue_ready=true;}
    library.job=JOB_NONE;
}
static void queue_step(void){
    if(!library.stage){if(!ln_music_db_request(&library.db,LN_DB_GROUP,library.queue_job_group)){fail(LN_DB_ARGUMENT);return;}library.stage=1;return;}
    int result=ln_music_db_step(&library.db);if(result<0){fail(result);return;}if(!result)return;
    if(library.stage==1){if(library.queue_job_ordinal>=library.db.group.count){queue_complete(UINT32_MAX);return;}
        if(!ln_music_db_request(&library.db,LN_DB_MEMBER,library.db.group.first+library.queue_job_ordinal)){fail(LN_DB_ARGUMENT);return;}
        library.stage=2;return;}
    queue_complete(library.db.member);
}
static bool query_admit(enum job job,uint32_t index,uint32_t ordinal)
{
    if(!ready()||library.query_pending||library.query_ready)return false;
    library.query=job;library.query_index=index;library.query_ordinal=ordinal;
    library.query_pending=true;return true;
}
bool ln_music_library_search(const char *prefix)
{ return ln_music_library_search_at(prefix,0); }
bool ln_music_library_search_at(const char *prefix,uint32_t ordinal)
{
    if(!prefix)return false;
    uint32_t n=0;while(n<256&&prefix[n])n++;
    if(n==256||!query_admit(JOB_SEARCH,0,ordinal))return false;
    text_copy(library.prefix,prefix);return true;
}
bool ln_music_library_take_search(uint32_t *index)
{
    if(!index||!ready()||library.query!=JOB_SEARCH||!library.query_ready)return false;
    *index=library.query_result;library.query_ready=false;return true;
}
bool ln_music_library_take_search_row(struct ln_music_library_search_row *out)
{
    if(!out||!ready()||library.query!=JOB_SEARCH||!library.query_ready)return false;
    out->index=library.query_result;text_copy(out->title,library.group_name);
    out->kind=library.query_result!=UINT32_MAX&&(library.query_result&LN_MUSIC_SEARCH_GROUP)?library.group.kind:0;
    out->count=out->kind?library.group.count:0;
    library.query_ready=false;return true;
}
bool ln_music_library_view_row(uint32_t source,uint32_t group,uint32_t ordinal)
{
    group&=~LN_QUEUE_REVERSE;
    if(!ready()||source>2)return false;
    if(source==2)return group<library.db.groups&&query_admit(JOB_VIEW_GROUP,group,ordinal);
    return ordinal<library.db.tracks&&query_admit(JOB_VIEW,ordinal,0);
}
bool ln_music_library_take_view_row(struct ln_music_library_search_row *out)
{
    if(!out||!ready()||!library.query_ready||
       (library.query!=JOB_VIEW&&library.query!=JOB_VIEW_GROUP))return false;
    out->index=library.query_result;text_copy(out->title,library.group_name);
    out->kind=out->count=0;
    library.query_ready=false;return true;
}
bool ln_music_library_track_record(uint32_t index){return ready()&&index<library.db.tracks&&query_admit(JOB_TRACK_RECORD,index,0);}
bool ln_music_library_track_ids(uint32_t first){return ready()&&first<library.db.tracks&&query_admit(JOB_TRACK_IDS,first,0);}
bool ln_music_library_take_track_ids(uint64_t ids[LN_MUSIC_ID_BATCH],uint32_t *count){
    if(!ids||!count||!ready()||library.query!=JOB_TRACK_IDS||!library.query_ready)return false;
    *count=library.query_result;for(uint32_t i=0;i<*count;i++)ids[i]=library.ids[i];library.query_ready=false;return true;
}
bool ln_music_library_take_track_record(struct ln_music_track *out){
    if(!out||!ready()||library.query!=JOB_TRACK_RECORD||!library.query_ready)return false;
    *out=library.record;library.query_ready=false;return true;
}
bool ln_music_library_group(uint32_t index)
{
    return ready()&&index<library.db.groups&&query_admit(JOB_GROUP,index,0);
}
bool ln_music_library_group_record(uint32_t index)
{
    return ready()&&index<library.db.groups&&query_admit(JOB_GROUP_RECORD,index,0);
}
bool ln_music_library_take_group(struct ln_music_group *out,char name[256])
{
    if(!out||!name||!ready()||(library.query!=JOB_GROUP&&library.query!=JOB_GROUP_RECORD)||!library.query_ready)return false;
    *out=library.group;text_copy(name,library.group_name);library.query_ready=false;return true;
}
bool ln_music_library_group_member(uint32_t index,uint32_t ordinal)
{
    index&=~LN_QUEUE_REVERSE;return ready()&&index<library.db.groups&&query_admit(JOB_MEMBER,index,ordinal);
}
bool ln_music_library_take_member(uint32_t *index)
{
    if(!index||!ready()||library.query!=JOB_MEMBER||!library.query_ready)return false;
    *index=library.query_result;library.query_ready=false;return true;
}
static bool request(enum ln_music_db_request operation,uint32_t index)
{
    if(ln_music_db_request(&library.db,operation,index))return true;
    fail(LN_DB_FORMAT);return false;
}
static void row_complete(void)
{
    if(!ln_music_db_safe_path(library.scratch.path)){fail(LN_DB_FORMAT);return;}
    uint32_t index=library.scratch.index;
    if(index>=library.first&&index-library.first<LN_MUSIC_LIBRARY_ROWS){
        uint32_t slot=index-library.first;
        library.rows[slot]=library.scratch;library.valid[slot]=true;
        if(slot%6u==5u||index+1u==library.db.tracks||library.job==JOB_SELECTION)changed();
    }
    if(library.job==JOB_SELECTION&&library.job_token==library.selection_token){
        library.selection=library.scratch;library.selection_ready=true;
        library.selection_pending=false;
    }
    if(library.job==JOB_PREFETCH&&library.job_token==library.prefetch_token){
        library.prefetch=library.scratch;library.prefetch_ready=true;library.prefetch_pending=false;
    }
    library.job=JOB_NONE;
}
static void row_step(void)
{
    if(!library.stage){
        clear(&library.scratch,sizeof(library.scratch));library.scratch.index=library.job_index;
        if(request(LN_DB_TRACK,library.job_index))library.stage=1;
        return;
    }
    int result=ln_music_db_step(&library.db);
    if(result<0){fail(result);return;}if(!result)return;
    if(library.stage==1){library.scratch.track=library.db.track;if(request(LN_DB_STRING,library.scratch.track.title))library.stage=2;}
    else if(library.stage==2){text_copy(library.scratch.title,library.db.text);if(request(LN_DB_STRING,library.scratch.track.artist))library.stage=3;}
    else if(library.stage==3){
        text_copy(library.scratch.artist,library.db.text);
        if(library.job!=JOB_WINDOW){if(request(LN_DB_STRING,library.scratch.track.album))library.stage=7;}
        else if(request(LN_DB_STRING,library.scratch.track.path))library.stage=4;
    }
    else if(library.stage==7){
        text_copy(library.scratch.album,library.db.text);library.scratch.album_ready=true;
        if(request(LN_DB_STRING,library.scratch.track.path))library.stage=4;
    }
    else if(library.stage==8){
        text_copy(library.scratch.album,library.db.text);library.scratch.album_ready=true;
        if(library.scratch.track.art!=UINT32_MAX&&!library.scratch.art_path[0]){
            if(request(LN_DB_ART,library.scratch.track.art))library.stage=5;
        }else row_complete();
    }
    else if(library.stage==4){
        text_copy(library.scratch.path,library.db.text);
        if(library.job!=JOB_WINDOW&&library.scratch.track.art!=UINT32_MAX){
            if(request(LN_DB_ART,library.scratch.track.art))library.stage=5;
        }else row_complete();
    }else if(library.stage==5){library.scratch.art_crc=library.db.art.crc;
        if(request(LN_DB_STRING,library.db.art.path))library.stage=6;
    }else{
        static const char prefix[]="/.LINNET/ART/";
        bool valid=ln_music_db_safe_path(library.db.text);
        for(uint32_t i=0;i<sizeof prefix-1u;++i)if(library.db.text[i]!=prefix[i])valid=false;
        if(!valid){fail(LN_DB_FORMAT);return;}
        text_copy(library.scratch.art_path,library.db.text);row_complete();
    }
}
static void query_complete(uint32_t result)
{
    library.query_result=result;library.query_pending=false;library.query_ready=true;
    library.job=JOB_NONE;
    /* The consuming view publishes visible changes; offscreen prefetch must not repaint. */
}
static void query_step(void)
{
    if(library.job==JOB_TRACK_IDS){
        uint32_t count=library.db.tracks-library.query_index;if(count>LN_MUSIC_ID_BATCH)count=LN_MUSIC_ID_BATCH;
        int result=read_database(0,library.db.track_offset+library.query_index*LN_MUSIC_TRACK_BYTES,library.db.buffer,count*LN_MUSIC_TRACK_BYTES);
        if(result<0){fail(result);return;}if(!result)return;
        for(uint32_t i=0;i<count;i++)library.ids[i]=ln_read_le64(library.db.buffer+i*LN_MUSIC_TRACK_BYTES);
        query_complete(count);return;
    }
    if(!library.stage){
        if(library.job==JOB_VIEW||library.job==JOB_TRACK_RECORD){
            library.query_result=library.query_index;library.group_name[0]=0;
            if(request(LN_DB_TRACK,library.query_index))library.stage=2;
            return;
        }
        if(library.job==JOB_SEARCH){if(!ln_music_db_search_at(&library.db,library.prefix,library.query_ordinal)){fail(LN_DB_ARGUMENT);return;}}
        else if(!request(LN_DB_GROUP,library.query_index))return;
        library.stage=1;return;
    }
    int result=ln_music_db_step(&library.db);
    if(result<0){fail(result);return;}if(!result)return;
    if(library.job==JOB_TRACK_RECORD){library.record=library.db.track;query_complete(library.query_index);return;}
    if(library.job==JOB_VIEW_GROUP&&library.stage==1){
        library.group_name[0]=0;
        if(library.query_ordinal>=library.db.group.count){query_complete(UINT32_MAX);return;}
        if(request(LN_DB_MEMBER,library.db.group.first+library.query_ordinal))library.stage=4;
        return;
    }
    if(library.job==JOB_VIEW_GROUP&&library.stage==4){
        library.query_result=library.db.member;
        if(request(LN_DB_TRACK,library.query_result))library.stage=2;
        return;
    }
    if(library.job==JOB_SEARCH||library.job==JOB_VIEW||library.job==JOB_VIEW_GROUP){
        if(library.stage==1){
            library.query_result=library.db.search_track;library.group_name[0]=0;
            if(library.query_result==UINT32_MAX){query_complete(UINT32_MAX);return;}
            if(library.query_result&LN_MUSIC_SEARCH_GROUP){
                if(request(LN_DB_GROUP,library.query_result&~LN_MUSIC_SEARCH_GROUP))library.stage=5;
                return;
            }
            if(request(LN_DB_TRACK,library.query_result))library.stage=2;
        }else if(library.stage==5){
            library.group=library.db.group;
            if(library.group.kind!=1&&library.group.kind!=2){fail(LN_DB_FORMAT);return;}
            if(request(LN_DB_STRING,library.group.name))library.stage=3;
        }else if(library.stage==2){
            if(request(LN_DB_STRING,library.db.track.title))library.stage=3;
        }else {text_copy(library.group_name,library.db.text);query_complete(library.query_result);}
        return;
    }
    if(library.stage==1){
        library.group=library.db.group;
        if(library.job==JOB_GROUP_RECORD){library.group_name[0]=0;query_complete(library.query_index);return;}
        if(library.job==JOB_GROUP){if(request(LN_DB_STRING,library.group.name))library.stage=2;}
        else if(library.query_ordinal>=library.group.count)query_complete(UINT32_MAX);
        else if(request(LN_DB_MEMBER,library.group.first+library.query_ordinal))library.stage=2;
        return;
    }
    if(library.job==JOB_GROUP){text_copy(library.group_name,library.db.text);query_complete(library.query_index);}
    else query_complete(library.db.member);
}
static void library_step_once(void)
{
    if(library.status==LN_LIBRARY_DRAINING){
        if(library.io_active){
            if(!ln_storage_media_poll(library.generation,0,0))return;
            library.io_active=false;library.io_buffer=0;
        }
        if(library.reopen)start();
        else{library.status=library.error?LN_LIBRARY_ERROR:LN_LIBRARY_CLOSED;library.job=JOB_NONE;changed();}
        return;
    }
    if(library.status==LN_LIBRARY_CLOSED||library.status==LN_LIBRARY_ERROR)return;
    if(library.status==LN_LIBRARY_OPENING){
        if(!library.io_active){
            if(library.paused)return;
            int result=ln_storage_media_open("/.LINNET/LIBRARY.PDB",library.generation);
            if(result<0){fail(result);return;}if(!result)return;
            library.io_active=true;return;
        }
        int result=ln_storage_media_poll(library.generation,&library.file,0);
        if(!result)return;
        library.io_active=false;
        if(result<0){fail(result);return;}
        ln_music_db_init(&library.db,read_database,0,library.file.size,library.generation);
        library.generation=next_generation();
        library.status=LN_LIBRARY_VERIFYING;changed();return;
    }
    if(library.status==LN_LIBRARY_VERIFYING){
        int result=ln_music_db_open_step(&library.db);
        if(result<0)fail(result);
        else if(result==1){library.status=LN_LIBRARY_READY;changed();}
        return;
    }
    if(retire_superseded_job())return;
    if(library.job==JOB_NONE){
        library.stage=0;
        if(library.selection_pending){
            const struct ln_music_library_row *cached=ln_music_library_row(library.selection_index);
            if(cached&&cached->album_ready&&(cached->track.art==UINT32_MAX||cached->art_path[0])){library.selection=*cached;library.selection_pending=false;library.selection_ready=true;return;}
            library.job=JOB_SELECTION;library.job_index=library.selection_index;library.job_token=library.selection_token;
        }else if(library.prefetch_pending){
            const struct ln_music_library_row *cached=ln_music_library_row(library.prefetch_index);
            if(cached&&cached->album_ready&&(cached->track.art==UINT32_MAX||cached->art_path[0])){library.prefetch=*cached;library.prefetch_pending=false;library.prefetch_ready=true;return;}
            library.job=JOB_PREFETCH;library.job_index=library.prefetch_index;library.job_token=library.prefetch_token;
            if(cached){
                /* Window rows already prove track, title, artist and media path.
                 * Resolve only missing playback metadata under the same owner. */
                library.scratch=*cached;
                if(!cached->album_ready){
                    if(request(LN_DB_STRING,cached->track.album))library.stage=8;
                }else if(request(LN_DB_ART,cached->track.art))library.stage=5;
                return;
            }
        }else if(library.queue_pending){library.job=JOB_QUEUE;
            library.queue_job_group=library.queue_group;library.queue_job_ordinal=library.queue_ordinal;library.queue_job_token=library.queue_token;
        }else if(library.query_pending)library.job=library.query;
        else if(window_enabled){
            for(uint32_t i=0;i<LN_MUSIC_LIBRARY_ROWS;i++){
                if(library.first>=library.db.tracks||i>=library.db.tracks-library.first)break;
                if(!library.valid[i]){library.job=JOB_WINDOW;library.job_index=library.first+i;break;}
            }
        }
    }
    if(library.job==JOB_WINDOW||library.job==JOB_SELECTION||library.job==JOB_PREFETCH)row_step();
    else if(library.job==JOB_QUEUE)queue_step();
    else if(library.job!=JOB_NONE)query_step();
}

void ln_music_library_step(void)
{
    for(uint32_t step=0;step<32u;step++){
        library_step_once();
        if(!ready()||library.io_active||library.paused||library.job==JOB_NONE)break;
    }
}

/* Only the outer controller may pump additional metadata work. */
bool ln_music_library_can_continue(void)
{
    return ready()&&!library.paused&&!library.io_active;
}
