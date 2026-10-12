#include "coverflow.h"
#if defined(LINNET_COVERFLOW)
#include "services/music/library.h"
#include "services/music/browser.h"
#include "services/storage/storage.h"
#include "boot/include/linnet_boot.h"
#include "boot/include/linnet_bytes.h"
#include "hal/api/platform.h"
#define CATALOG_SLOTS LINNET_COVERFLOW_CATALOG_SLOTS
#define CATALOG_RECORD 1024u
#define ART_RECORD 13312u
#if LINNET_COVERFLOW_SCANLINE
#define COVER_MAGIC 0x4e46434cu
#define TILE_RECORD 23552u
#define TEXTURE_WIDTH 130u
#define TEXTURE_HEIGHT 174u
#define SLOTS 6u
#else
#define COVER_MAGIC 0x3246434cu
#define TILE_RECORD ART_RECORD
#define TEXTURE_WIDTH 96u
#define TEXTURE_HEIGHT 128u
#define SLOTS 16u
#endif
#define ART_LOW 630u
#if LINNET_COVERFLOW_EXPANDED
#define PAGE 64u
#define ART_PAGE 14u
#define ART_HIGH 1418u
#else
#define PAGE 16u
#define ART_PAGE 7u
#if LINNET_COVERFLOW_SCANLINE
/* Reserve three old tile units for the independent playback preview. */
#define ART_HIGH 466u
#else
#define ART_HIGH 469u
#endif
#endif
#define ART_SLOTS (ART_LOW+ART_HIGH)
#define NONE UINT32_MAX
#define COVER_WIDTH (96u*LINNET_UI_HEIGHT/176u)
enum {CLOSED,OPEN,HEADER,READY,CATALOG,ART};
/* Valid IDs publish only after a complete decode; pixel storage needs no reset. */
static uint16_t cache_pixels[SLOTS][TEXTURE_WIDTH*TEXTURE_HEIGHT] __attribute__((section(".media_workspace"),aligned(32)));
static struct {uint32_t id,age;} cache[SLOTS];
static uint32_t age;
#if LINNET_COVERFLOW_EXPANDED
static uint8_t catalog[CATALOG_SLOTS][CATALOG_RECORD] __attribute__((section(".cover_catalog"),aligned(32)));
#else
/* Tags stay in cleared BSS and publish only validated, complete records.
 * The unread payload needs no boot-time clear, like the artwork banks. */
static uint8_t catalog[CATALOG_SLOTS][CATALOG_RECORD] __attribute__((section(".media_workspace"),aligned(32)));
#endif
static uint32_t tags[CATALOG_SLOTS];
static uint8_t *catalog_extra;
static uint32_t *catalog_extra_tags,catalog_capacity=CATALOG_SLOTS;
static struct ln_fat32_file file;
static uint8_t header[1024] __attribute__((aligned(32)))
#if defined(LINNET_COVERFLOW_HEADER_SECTION)
    __attribute__((section(LINNET_COVERFLOW_HEADER_SECTION)))
#endif
;
static uint8_t art_low[ART_LOW*ART_RECORD] __attribute__((section(".cover_low"),aligned(32)));
static uint8_t art_high[ART_HIGH*ART_RECORD] __attribute__((section(".cover_high"),aligned(32)));
static uint32_t art_tags[ART_SLOTS],art_warm,art_loaded,art_base,art_end,art_remaining;
static bool art_bulk;
#define ART_LOW_SLOTS (sizeof art_low/TILE_RECORD)
#define ART_CAPACITY (ART_LOW_SLOTS+sizeof art_high/TILE_RECORD)
#if LINNET_COVERFLOW_SCANLINE
extern const uint8_t ln_coverflow_preview_x[130],ln_coverflow_preview_y[174];
#endif
static uint8_t *art_record(uint32_t id){uint32_t slot=id%ART_CAPACITY;return slot<ART_LOW_SLOTS?art_low+slot*TILE_RECORD:art_high+(slot-ART_LOW_SLOTS)*TILE_RECORD;}
static bool art_ready(uint32_t id){return art_tags[id%ART_CAPACITY]==id+1u;}
static uint32_t count,arts,selected,phase,loading,length,revision,drawn,next,io_due,warm,moved_at;
static uint32_t catalog_loaded,full_reads,read_bytes,hits,preview_hits,misses,last_full_us,max_full_us,last_preview_us;
static int32_t position,direction=1;
static bool visible,pending,failed,canceling,moved_in_visit,mapped_art;
static enum ln_music_library_status displayed_library_status=LN_LIBRARY_CLOSED;
static const uint32_t generation=0x79000001u;
struct ln_coverflow_column {uint32_t step;uint8_t source,top,height,length;};
extern const struct ln_coverflow_column ln_coverflow_columns[33][COVER_WIDTH];
extern const uint8_t ln_coverflow_widths[33];
#if LINNET_COVERFLOW_SCANLINE
extern const uint8_t ln_coverflow_glow_pairs[190][160];
extern const uint8_t ln_coverflow_glow_colors[2][192][2];
#else
extern const uint8_t ln_coverflow_glow[LINNET_UI_WIDTH][LINNET_UI_HEIGHT*140u/176u];
#endif
static bool identity(void){uint8_t hash[32];if(!ln_music_library_identity(hash))return false;
    for(uint32_t i=0;i<32;i++)if(hash[i]!=header[16+i])return false;return true;}
static uint8_t *catalog_record(uint32_t index){
    uint32_t slot=index%catalog_capacity;
    return slot<CATALOG_SLOTS?catalog[slot]:catalog_extra+(slot-CATALOG_SLOTS)*CATALOG_RECORD;
}
static uint32_t *catalog_tag(uint32_t index){
    uint32_t slot=index%catalog_capacity;
    return slot<CATALOG_SLOTS?tags+slot:catalog_extra_tags+slot-CATALOG_SLOTS;
}
static uint8_t *row(uint32_t index){
    if(catalog_extra&&!identity())return 0;
    return index<count&&*catalog_tag(index)==index+1u?catalog_record(index):0;
}
static void catalog_extend(void){
    uint32_t bytes=0;uint8_t *memory=ln_music_library_catalog_memory(&bytes);
    uint32_t extra=bytes/(CATALOG_RECORD+sizeof(uint32_t));extra=extra/PAGE*PAGE;
    if(!memory||!extra)return;
    catalog_extra_tags=(uint32_t*)memory;catalog_extra=memory+extra*sizeof(uint32_t);
    for(uint32_t i=0;i<extra;i++)catalog_extra_tags[i]=0;
    catalog_capacity=CATALOG_SLOTS+extra;
}
static int32_t find_art(uint32_t id){for(uint32_t i=0;i<SLOTS;i++)if(cache[i].id==id+1u)return (int32_t)i;return -1;}
static bool close_to_selection(uint32_t art);
static bool selected_full(void){uint8_t *r=row(selected);return r&&art_ready(ln_read_le32(r+248));}
static void invalidate(void){
    /* The library may already be reusing its tail for a new verification.
     * Drop the lease without clearing memory owned by that new generation. */
    catalog_extra=0;catalog_extra_tags=0;catalog_capacity=CATALOG_SLOTS;
    for(uint32_t i=0;i<CATALOG_SLOTS;i++)tags[i]=0;
    for(uint32_t i=0;i<SLOTS;i++)cache[i].id=0;
    for(uint32_t i=0;i<ART_SLOTS;i++)art_tags[i]=0;
    art_warm=art_loaded=art_base=art_end=art_remaining=0;art_bulk=false;
    count=arts=selected=warm=catalog_loaded=0;position=0;phase=CLOSED;++revision;
}
bool ln_coverflow_release_catalog(void){
    if(pending){
        if(!canceling){ln_storage_media_cancel(generation);canceling=true;}
        return false;
    }
    invalidate();failed=false;canceling=false;io_due=ln_time_us();return true;
}
static void rewind_art_warm(void){
    if(!art_bulk||loading<art_base||loading>=art_end)return;
    uint32_t n=length/TILE_RECORD;
    if(n>art_end-art_base-art_remaining)n=art_end-art_base-art_remaining;
    art_remaining+=n;art_warm=loading;
}
void ln_coverflow_visible(bool value){
    if(value&&!visible){moved_in_visit=false;io_due=ln_time_us();}
    if(!value)moved_in_visit=false;
    visible=value;
}
uint32_t ln_coverflow_count(void){return count;}
bool ln_coverflow_active(void){return visible;}
bool ln_coverflow_move(int32_t delta){
    if(!count||!delta)return false;int32_t n=(int32_t)selected+(delta>64?64:delta< -64?-64:delta);
    uint32_t target=n<0?0u:(uint32_t)n>=count?count-1u:(uint32_t)n;if(target==selected)return false;
    int32_t moving=target>selected?1:-1;
    direction=moving;
    if(target/catalog_capacity!=selected/catalog_capacity)warm=(target/catalog_capacity)*catalog_capacity;
    selected=target;
    if(phase==ART&&!canceling){
        bool needed=false;
        for(uint32_t i=0;i<length/TILE_RECORD;i++)if(close_to_selection(loading+i)){needed=true;break;}
        if(!needed){
            if(pending){ln_storage_media_cancel(generation);canceling=true;}
            else {rewind_art_warm();phase=READY;}
        }
    }
    int32_t distance=(int32_t)(selected*256u)-position;
    if(distance>512)position=(int32_t)(selected*256u)-512;
    else if(distance< -512)position=(int32_t)(selected*256u)+512;
    moved_at=ln_time_us();io_due=moved_at;
    moved_in_visit=visible;
    if(selected_full()){++hits;last_full_us=0;}else if(row(selected))++preview_hits;else ++misses;
    last_preview_us=row(selected)?0u:NONE;
    ++revision;next=0;return true;
}
const char *ln_coverflow_text(bool artist){
    enum ln_music_library_status status=ln_music_library_status();
    if(status==LN_LIBRARY_ERROR&&ln_music_library_error()==LN_MUSIC_LIBRARY_RECOVERY_REQUIRED)
        return artist?"":"Recover music in Media Manager";
    if(status==LN_LIBRARY_ERROR&&ln_music_library_error()==LN_FAT32_NOT_FOUND)
        return artist?"":"No albums";
    if(status==LN_LIBRARY_ERROR)return artist?"":"Music library unavailable";
    if(status==LN_LIBRARY_READY&&!ln_music_library_count())return artist?"":"No albums";
    if(failed)return artist?"Sync music to prepare artwork":"Cover Flow needs a sync";
    if(!count)return artist?"":phase>=READY?"No albums":"Albums";
    uint8_t *r=row(selected);return r?(const char*)r+(artist?128:8):(artist?"":"Albums");
}
bool ln_coverflow_select(void){uint8_t *r=row(selected);return r&&identity()&&
    ln_music_browser_open_album(ln_read_le32(r),ln_read_le32(r+4),(const char*)r+8);}
static void fail(void){failed=true;phase=CLOSED;io_due=NONE;++revision;}
static void request_catalog(uint32_t index){
    loading=(index/PAGE)*PAGE;length=count-loading;if(length>PAGE)length=PAGE;
    uint32_t slot=loading%catalog_capacity,available=slot<CATALOG_SLOTS?CATALOG_SLOTS-slot:catalog_capacity-slot;
    if(length>available)length=available;
    for(uint32_t i=0;i<length;i++)*catalog_tag(loading+i)=0;
    length*=CATALOG_RECORD;phase=CATALOG;
}
static bool close_to_selection(uint32_t art){
    for(int32_t d=-3;d<=3;d++){int32_t n=(int32_t)selected+d;if(n<0)continue;
        uint8_t *r=row((uint32_t)n);if(r&&ln_read_le32(r+248)==art)return true;}
    return false;
}
static bool warm_protected(uint32_t art){
    uint32_t tag=art_tags[art%ART_CAPACITY];
    return tag&&tag!=art+1u&&close_to_selection(tag-1u);
}
static void art_warm_window(void){
    uint32_t base=0,end=arts<ART_CAPACITY?arts:ART_CAPACITY,anchor=0;
    if(arts>ART_CAPACITY){
        bool found=false;
        /* New image IDs follow album order; shared covers can point backward.
         * Nearby novel artwork keeps late albums in their own cache region. */
        for(int32_t d=-3;d<=3;d++){
            int32_t index=(int32_t)selected+d;if(index<0)continue;
            uint8_t *r=row((uint32_t)index);if(!r)continue;
            uint32_t id=ln_read_le32(r+248);if(!found||id>anchor)anchor=id;found=true;
        }
        if(!found)return;
        base=anchor>ART_CAPACITY/2u?anchor-ART_CAPACITY/2u:0u;
        if(base>arts-ART_CAPACITY)base=arts-ART_CAPACITY;
        end=base+ART_CAPACITY;
    }
    if(base==art_base&&end==art_end)return;
    art_base=base;art_end=end;art_remaining=end-base;
    /* Start near the selection, then wrap once through the bounded region. */
    art_warm=direction<0&&anchor>base+64u?anchor-64u:anchor;
    if(art_warm<base||art_warm>=end)art_warm=base;
}
static void advance_art_warm(uint32_t n){
    art_remaining-=n;art_warm+=n;if(art_warm==art_end)art_warm=art_base;
}
static uint32_t decode_priority(uint32_t art){
#if LINNET_COVERFLOW_SCANLINE
    static const int8_t ahead[]={0,1,-1,2,-2,3};
    uint32_t limit=position==(int32_t)(selected*256u)?6u:3u;
    for(uint32_t i=0;i<limit;i++){
        int32_t index=(int32_t)selected+ahead[i]*direction;
        if(index<0)continue;uint8_t *r=row((uint32_t)index);
        if(r&&ln_read_le32(r+248)==art)return i<3u?2u:1u;
    }
#else
    (void)art;
#endif
    return 0;
}
static int32_t decode_art(uint32_t id){
    int32_t found=find_art(id);if(found>=0)return found;
    if(!art_ready(id))return -1;
    uint32_t victim=0,oldest=NONE,priority=3u;
    for(uint32_t i=0;i<SLOTS;i++){
        if(!cache[i].id){victim=i;break;}
        uint32_t rank=decode_priority(cache[i].id-1u);
        if(rank<priority||(rank==priority&&cache[i].age<oldest)){
            priority=rank;oldest=cache[i].age;victim=i;
        }
    }
    const uint8_t *packed=art_record(id);
    union {uint16_t colors[256];uint32_t words[128];} palette;
    const uint32_t *words=(const uint32_t*)packed;
    for(uint32_t i=0;i<128u;i++)palette.words[i]=words[i];
    words+=128;
    for(uint32_t i=0;i<TEXTURE_WIDTH*TEXTURE_HEIGHT;i+=4){
        uint32_t indices=*words++;
        cache_pixels[victim][i]=palette.colors[indices&255u];
        cache_pixels[victim][i+1]=palette.colors[(indices>>8)&255u];
        cache_pixels[victim][i+2]=palette.colors[(indices>>16)&255u];
        cache_pixels[victim][i+3]=palette.colors[indices>>24];
    }
    cache[victim].id=id+1u;cache[victim].age=++age;
    return (int32_t)victim;
}
const uint16_t *ln_coverflow_playback_preview(const char *path,uint32_t crc){
#if LINNET_COVERFLOW_SCANLINE
    static const char prefix[]="/.LINNET/ART/";
    if(!mapped_art||failed||!identity()||!path)return 0;
    for(uint32_t i=0;i<sizeof prefix-1u;i++)if(path[i]!=prefix[i])return 0;
    uint32_t hash=0;
    for(uint32_t i=0;i<8u;i++){
        uint32_t c=(uint8_t)path[sizeof prefix-1u+i],v;
        if(c>='0'&&c<='9')v=c-'0';else if(c>='A'&&c<='F')v=c-'A'+10u;else return 0;
        hash|=v<<((i/2u)*8u+(i%2u?0u:4u));
    }
    const char *tail=path+sizeof prefix-1u+8u;
    if(tail[0]!='.'||tail[1]!='R'||tail[2]!='G'||tail[3]!='B'||tail[4])return 0;
    uint8_t *r=row(selected);int32_t slot=-1;
    if(r&&ln_read_le32(r+240)==hash&&ln_read_le32(r+244)==crc)
        slot=decode_art(ln_read_le32(r+248));
    /* Songs, queue changes and resume can request any retained album. Only
     * published catalog rows may bind its exact playback path and checksum. */
    for(uint32_t i=0;slot<0&&i<catalog_capacity;i++){
        uint32_t tag=*catalog_tag(i);if(!tag||tag>count)continue;
        r=row(tag-1u);if(!r)continue;
        if(ln_read_le32(r+240)==hash&&ln_read_le32(r+244)==crc)
            slot=decode_art(ln_read_le32(r+248));
    }
    if(slot>=0){cache[slot].age=++age;return cache_pixels[slot];}
#else
    (void)path;(void)crc;
#endif
    return 0;
}
static void request_art(uint32_t id,bool bulk){
    loading=id;length=1u;art_bulk=bulk;
    uint32_t slot=id%ART_CAPACITY,available=slot<ART_LOW_SLOTS?ART_LOW_SLOTS-slot:ART_CAPACITY-slot;
    if(bulk)while((length+1u)*TILE_RECORD<=ART_PAGE*ART_RECORD&&length<available&&
        length<art_remaining&&loading+length<art_end&&!art_ready(loading+length)&&
        !warm_protected(loading+length))++length;
    for(uint32_t i=0;i<length;i++)art_tags[(loading+i)%ART_CAPACITY]=0;
    length*=TILE_RECORD;phase=ART;
}
static void accept_art(void){
    for(uint32_t i=0;i<length/TILE_RECORD;i++){
        uint32_t id=loading+i;const uint8_t *packed=art_record(id);
        uint32_t end=512u+TEXTURE_WIDTH*TEXTURE_HEIGHT;
        if(ln_crc32(packed,end)!=ln_read_le32(packed+end)){fail();return;}
        art_tags[id%ART_CAPACITY]=id+1u;++art_loaded;
        if(close_to_selection(id))++revision;
        uint8_t *r=row(selected);
        if(r&&ln_read_le32(r+248)==id&&moved_in_visit){
            last_full_us=ln_time_us()-moved_at;
            if(last_full_us>max_full_us)max_full_us=last_full_us;
        }
    }
}
void ln_coverflow_step(bool allow_read){
    if(pending){
        uint32_t transferred=0,began=ln_time_us();int result;
        for(uint32_t step=0;;step++){
            result=ln_storage_media_poll_deferred(generation,phase==OPEN?&file:0,&transferred);
            if(result||step==3u)break;
            uint32_t now=ln_time_us(),deadline;
            if(now-began>=500u||(ln_storage_idle_wait(now,&deadline)&&(int32_t)(deadline-now)>0))break;
        }
        if(!result){io_due=ln_time_us()+1000u;return;}pending=false;
        if(result<0){
            if(canceling&&result==LN_FAT32_STALE){
                canceling=false;rewind_art_warm();
                phase=READY;io_due=ln_time_us();return;
            }
            fail();return;
        }
        canceling=false;
        if(phase==OPEN){phase=HEADER;}
        else if(phase==HEADER){
            count=ln_read_le32(header+4);arts=ln_read_le32(header+52);
            uint32_t magic=ln_read_le32(header);
            mapped_art=LINNET_COVERFLOW_SCANLINE;
            if(transferred!=1024||magic!=COVER_MAGIC||count>100000u||arts>count||
               ln_read_le32(header+8)!=TILE_RECORD||ln_read_le32(header+12)!=TEXTURE_WIDTH||ln_read_le32(header+48)!=CATALOG_RECORD||
               (LINNET_COVERFLOW_SCANLINE&&ln_read_le32(header+68)!=1u)||
               ln_read_le32(header+56)!=24||ln_read_le32(header+60)!=32||
               ln_crc32(header,508)!=ln_read_le32(header+508)||ln_crc32(header+512,512)!=ln_read_le32(header+64)||
               file.size!=1024u+count*CATALOG_RECORD+arts*TILE_RECORD||!identity()){
                count=0;fail();return;}
            catalog_extend();phase=READY;++revision;
        }else if(phase==CATALOG){
            if(transferred!=length){fail();return;}
            for(uint32_t i=0;i<length/CATALOG_RECORD;i++){
                uint32_t index=loading+i;uint8_t *r=catalog_record(index);
                uint32_t crc=ln_crc32_update(ln_crc32_update(0xffffffffu,r,252),r+256,768);
                if((~crc)!=ln_read_le32(r+252)||r[127]||r[LINNET_COVERFLOW_SCANLINE?239u:247u]||ln_read_le32(r+248)>=arts||
                   ln_read_le32(r)>=ln_music_library_group_count()||!ln_read_le32(r+4)||ln_read_le32(r+4)>ln_music_library_count()){
                    fail();return;}
                *catalog_tag(index)=index+1u;++catalog_loaded;
            }
            if(selected>=loading&&selected<loading+length/CATALOG_RECORD){
                if(moved_in_visit)
                    last_preview_us=ln_time_us()-moved_at;
                ++revision;
            }
            else if(visible&&loading<selected+4u&&loading+length/CATALOG_RECORD+3u>selected)++revision;
            phase=READY;
        }else if(phase==ART){
            if(transferred!=length){fail();return;}
            accept_art();if(failed)return;phase=READY;
        }
    }
    uint32_t now=ln_time_us();
    if(failed){io_due=NONE;return;}
    enum ln_music_library_status status=ln_music_library_status();
    if(status==LN_LIBRARY_ERROR||(status==LN_LIBRARY_READY&&!ln_music_library_count())){
        if(phase!=CLOSED||count)invalidate();
        io_due=NONE;return;
    }
    if(!allow_read||status!=LN_LIBRARY_READY){
        io_due=now+10000u;return;
    }
    if(phase>=READY&&!identity())invalidate();
    if(phase==READY){
        if(count&&!row(selected))request_catalog(selected);
        else if(count){
            static const int8_t ahead[]={0,1,-1,2,-2,3,-3};
            bool decoded=false;
            for(uint32_t d=0;d<sizeof(ahead);d++){
                if(d>=3u&&(!visible||(uint32_t)(now-moved_at)<120000u))break;
                int32_t index=(int32_t)selected+ahead[d]*direction;
                if(index<0||(uint32_t)index>=count)continue;
                uint8_t *r=row((uint32_t)index);if(!r){request_catalog((uint32_t)index);break;}
                uint32_t art=ln_read_le32(r+248);
                if(!art_ready(art)){request_art(art,false);break;}
#if LINNET_COVERFLOW_SCANLINE
                uint32_t decode_limit=position==(int32_t)(selected*256u)?6u:3u;
#else
                uint32_t decode_limit=7u;
#endif
                if(visible&&d<decode_limit&&find_art(art)<0){
                    (void)decode_art(art);
#if !LINNET_COVERFLOW_SCANLINE
                    ++revision;
#endif
                    /* Indexed and decoded native pixels are identical. Cache
                     * preparation alone does not require another LCD frame. */
                    decoded=true;break;
                }
            }
            if(decoded){io_due=now+1000u;return;}
        }
        if(phase==READY){
            uint32_t base=count<=catalog_capacity?0u:(selected>128u?((selected-128u)/PAGE)*PAGE:0u);
            uint32_t end=count<=catalog_capacity?count:selected+128u;if(end>count)end=count;
            if(warm<base||warm>=end)warm=base;
            for(uint32_t n=0;warm<end&&n<catalog_capacity/PAGE;n++){
                uint32_t index=warm;warm+=PAGE;
                if(!row(index)){request_catalog(index);break;}
            }
        }
        if(phase==READY){
            art_warm_window();
            while(art_remaining&&(art_ready(art_warm)||warm_protected(art_warm)))advance_art_warm(1u);
            if(art_remaining&&(!visible||(uint32_t)(now-moved_at)>=300000u)){
                request_art(art_warm,true);advance_art_warm(length/TILE_RECORD);
            }
        }
        if(phase==READY){
            uint32_t elapsed=now-moved_at;
            io_due=visible&&count&&elapsed<120000u?moved_at+120000u:
                visible&&art_remaining&&elapsed<300000u?
                moved_at+300000u:NONE;
            return;
        }
    }
    int result;
    if(phase==CLOSED||phase==OPEN){phase=OPEN;result=ln_storage_media_open("/.LINNET/COVERS.CFL",generation);}
    else if(phase==HEADER)result=ln_storage_media_read(&file,0,header,1024,generation);
    else if(phase==CATALOG)result=ln_storage_media_read(&file,1024+loading*CATALOG_RECORD,catalog_record(loading),length,generation);
    else result=ln_storage_media_read(&file,1024+count*CATALOG_RECORD+loading*TILE_RECORD,art_record(loading),length,generation);
    if(result>0){pending=true;if(phase==ART){++full_reads;read_bytes+=length;}else if(phase==CATALOG)read_bytes+=length;}
    else if(result<0){fail();return;}
    io_due=now+1000u;
}
uint32_t ln_coverflow_io_deadline(void){return io_due;}
uint32_t ln_coverflow_deadline(void){return visible?next:NONE;}
uint32_t ln_coverflow_tick(uint32_t now){
    if(!visible)return 0;
    enum ln_music_library_status status=ln_music_library_status();
    if(status!=displayed_library_status){displayed_library_status=status;++revision;}
    if(next!=NONE&&next&&(int32_t)(now-next)<0)return 0;
    int32_t diff=(int32_t)(selected*256u)-position;
    if(diff){
        int32_t step=diff*2/3;
        position+=(step?step:diff);
    }
    uint32_t changed=drawn!=revision?1u:diff?8u:0u;drawn=revision;
    next=position!=(int32_t)(selected*256u)?now+20000u:NONE;
    return changed;
}
#if !defined(LINNET_PROFILE_RELEASE)
#if LINNET_COVERFLOW_SCANLINE
static uint32_t render_calls,render_us;
void ln_coverflow_render_diagnostics(uint32_t words[16]){
    uint32_t values[16]={0x52464c43u,render_calls,render_us,arts,art_warm,art_remaining,art_base,art_end};
    for(uint32_t i=0;i<16;i++)words[i]=values[i];
}
#endif
void ln_coverflow_diagnostics(uint32_t words[16]){
    uint32_t values[16]={0x574f4c46u,phase,count,selected,catalog_loaded,hits,preview_hits,misses,
        full_reads,read_bytes,last_full_us,art_loaded,max_full_us,selected_full(),row(selected)!=0,pending};
    for(uint32_t i=0;i<16;i++)words[i]=values[i];
}
#endif
static void ambient_color(uint32_t index,uint32_t color[3]){
    const uint8_t *r=row(index);color[0]=color[1]=color[2]=0;if(!r)return;
    for(uint32_t x=3;x<24;x+=6)for(uint32_t y=3;y<24;y+=6){
        uint32_t p=r[256+x*32+y];
        color[0]+=p>>5;color[1]+=(p>>2)&7;color[2]+=p&3;
    }
    color[0]=color[0]*255/112;color[1]=color[1]*255/112;color[2]=color[2]*255/48;
}
#if LINNET_COVERFLOW_SCANLINE
#include "services/music/coverflow_scanline.inc"
#else
void ln_coverflow_draw(const struct ln_ui_canvas_context *c){
    uint16_t painted_top[LINNET_UI_WIDTH],painted_end[LINNET_UI_WIDTH];
    for(uint32_t x=0;x<LINNET_UI_WIDTH;x++){painted_top[x]=LINNET_UI_HEIGHT;painted_end[x]=0;}
    int32_t center=(position+128)/256;
    for(int32_t layer=0;layer<=3;layer++)for(int32_t side=1;side>=-1;side-=2){
        if(!layer&&side==1)continue;
        int32_t index=center+layer*side;if(index<0||(uint32_t)index>=count)continue;
        uint8_t *r=row((uint32_t)index);
        uint32_t art=r?ln_read_le32(r+248):NONE;
        int32_t cached=r?find_art(art):-1;
        if(cached<0&&r&&layer<2)cached=decode_art(art);
        const uint16_t *pixels=cached>=0?cache_pixels[cached]:0;
        const uint8_t *indexed=!pixels&&r&&art_ready(art)?art_record(art):0;
        const uint16_t *palette=(const uint16_t*)indexed;
        if(cached>=0)cache[cached].age=++age;
        int32_t distance=index*256-position,ad=distance<0?-distance:distance;
        int32_t pose=ad>=256?32:(ad+4)/8,width=ln_coverflow_widths[pose];
        int32_t xcenter=LINNET_UI_WIDTH/2+(distance<0?-1:1)*(ad<=256?ad*69/256:69+(ad-256)*25/256)*(int32_t)LINNET_UI_WIDTH/220;
        for(int32_t x=0;x<width;x++){
            int32_t dx=xcenter-width/2+x;if(dx<c->clip_x||dx>=c->clip_x+c->clip_w)continue;
            const struct ln_coverflow_column *column=&ln_coverflow_columns[pose][distance<0?x:width-1-x];
            int32_t sx=distance<0?column->source:95-column->source;
            const uint16_t *source=pixels?pixels+sx*128:0;
            int32_t first=c->clip_y-column->top;if(first<0)first=0;
            int32_t end=c->clip_y+c->clip_h-column->top;if(end>column->length)end=column->length;
            if(first>=end)continue;
            int32_t ends[4]={first,end,0,0};
            if(painted_end[dx]>painted_top[dx]){
                int32_t hidden_top=painted_top[dx]-column->top,hidden_end=painted_end[dx]-column->top;
                if(ends[1]>hidden_top)ends[1]=hidden_top;
                ends[2]=first>hidden_end?first:hidden_end;ends[3]=end;
            }
            if(column->top+first<painted_top[dx])painted_top[dx]=(uint16_t)(column->top+first);
            if(column->top+end>painted_end[dx])painted_end[dx]=(uint16_t)(column->top+end);
            const uint8_t *indices=indexed?indexed+512+sx*128:0;
            for(uint32_t segment=0;segment<4;segment+=2){
                int32_t from=ends[segment],to=ends[segment+1];if(from>=to)continue;
                uint16_t *dest=c->pixels+(column->top+from)*LINNET_UI_WIDTH+dx;
                uint32_t step=column->step,sy=(step>>1)+(uint32_t)from*step;
                if(source){
                    for(int32_t y=from;y<to;y++,sy+=step,dest+=LINNET_UI_WIDTH)*dest=source[sy>>16];
                }else if(indices){
                    for(int32_t y=from;y<to;y++,sy+=step,dest+=LINNET_UI_WIDTH)*dest=palette[indices[sy>>16]];
                }else if(r){
                    const uint8_t *preview=r+256+(sx/4)*32;
                    for(int32_t y=from;y<to;y++,sy+=step,dest+=LINNET_UI_WIDTH)
                        *dest=ln_read_le16(header+512+2u*preview[sy>>18]);
                }else{
                    for(int32_t y=from;y<to;y++,sy+=step,dest+=LINNET_UI_WIDTH)*dest=sy<(96u<<16)?0x18e4u:0u;
                }
            }
        }
    }
    /* Paint only exposed background; the host supplies the soft halo mask. */
    if(count){
        uint32_t left=(uint32_t)position/256u,blend=(uint32_t)position&255u;
        uint32_t a[3],b[3];ambient_color(left,a);ambient_color(left+1u<count?left+1u:left,b);
        for(uint32_t channel=0;channel<3;channel++)a[channel]=(a[channel]*(256u-blend)+b[channel]*blend)>>8;
        int32_t mean=(int32_t)(a[0]+a[1]+a[2])/3;
        for(uint32_t channel=0;channel<3;channel++){
            int32_t value=mean+((int32_t)a[channel]-mean)*3/2;
            a[channel]=value<0?0u:value>255?255u:(uint32_t)value;
        }
        uint16_t colors[256];
        uint32_t rs=a[0]*70u*31u*2048u/(63u*100u*255u);
        uint32_t gs=a[1]*70u*63u*2048u/(63u*100u*255u);
        uint32_t bs=a[2]*70u*31u*2048u/(63u*100u*255u);
        for(uint32_t k=0;k<64;k++){
            uint32_t r=rs*k,g=gs*k,b=bs*k;
            for(uint32_t d=0;d<4;d++){
                uint32_t bias=d*512u+256u;
                colors[k*4+d]=(uint16_t)(((r+bias)>>11)<<11|((g+bias)>>11)<<5|((b+bias)>>11));
            }
        }
        int32_t bottom=c->clip_y+c->clip_h;if(bottom>(int32_t)(LINNET_UI_HEIGHT*140u/176u))bottom=LINNET_UI_HEIGHT*140u/176u;
        for(int32_t x=c->clip_x;x<c->clip_x+c->clip_w;x++){
            int32_t spans[4]={c->clip_y,painted_top[x],painted_end[x],bottom};
            if(painted_end[x]<=painted_top[x]){spans[1]=bottom;spans[2]=bottom;}
            for(uint32_t part=0;part<4;part+=2){
                int32_t from=spans[part],to=spans[part+1];
                if(from<c->clip_y)from=c->clip_y;if(to>bottom)to=bottom;if(from>=to)continue;
                uint16_t *dest=c->pixels+from*LINNET_UI_WIDTH+x;
                const uint8_t *mask=ln_coverflow_glow[x]+from;
                for(int32_t y=from;y<to;y++,dest+=LINNET_UI_WIDTH)*dest=colors[*mask++];
            }
        }
    }

}
#endif

#else
void ln_coverflow_draw(const struct ln_ui_canvas_context *c){(void)c;}
#endif
