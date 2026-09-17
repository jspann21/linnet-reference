#include "boot/include/linnet_bytes.h"
#include "photos.h"
#include "pimg.h"
#include "jpeg.h"
#include "services/storage/storage.h"
#include "services/music/player.h"
#include "hal/api/audio.h"
#include "hal/api/platform.h"
#include "boot/include/linnet_boot.h"
#define ROWS 20u
#define TILES 64u
#define WIDTH LINNET_PHOTO_WIDTH
#define HEIGHT LINNET_PHOTO_HEIGHT
#define EMPTY_ALBUM_RESUME 65535u
enum phase {OPEN,HEADER,VERIFY,IDLE,RECORD,TITLE,THUMB,LEVEL,TILE_RECORD,TILE_DATA,SOURCE,JPEG_OPEN,JPEG_LOAD,JPEG_DECODE,TILE_COMMIT};
struct row {uint32_t index;bool valid,album,thumb;char title[192];union {struct ln_pimg_album a;struct ln_pimg_photo p;} data;struct ln_ui_asset asset;};
struct tile {uint32_t index,age;bool valid;};
static struct {
    union {struct {uint16_t tiles[TILES][1024],thumbs[ROWS][4096];} pimg;uint8_t jpeg[262144];uint32_t photo_info[65535];} pixels;
    union {uint16_t frame[2][WIDTH*HEIGHT];struct {uint32_t album_counts[4096];uint8_t metadata[2u*WIDTH*HEIGHT*sizeof(uint16_t)-4096u*sizeof(uint32_t)];} verify;} surface;
    struct ln_photo_jpeg jpeg;
    struct ln_pimg_header header;struct ln_fat32_file file,jpeg_file;
    struct row rows[ROWS];struct tile tiles[TILES];struct ln_pimg_photo photo;struct ln_pimg_level levels[6];
    struct ln_ui_asset asset;
    uint32_t verify_cached,verify_cursor;bool metadata_valid;
    uint8_t scratch[8192],resume[16],tile_records[512],tile_hints[TILES];char title[192],album_title[192],source[128];
    uint32_t phase,view,album,first,count,photo_index,window_first,window_count,epoch,working,generation,revision,navigation;
    uint32_t io_bytes,verify_at,verify_crc,job_index,job_slot,level_count,level,zoom,rotation,tile_index,tile_slot,tile_crc,age;
    uint32_t tile_records_first,tile_records_count,tile_group_count,tile_group_cursor;
    uint32_t visible[64],visible_count,front,render_y,slide_at,jpeg_at,ready_tiles,resume_stage;
    uint8_t verify_record[64];uint32_t v_photos,v_levels,v_tiles,v_album,v_photo,v_level,v_width,v_height,v_text_bytes,v_more,v_code,v_min,jpeg_crc;
    int16_t map_x[WIDTH],map_y[HEIGHT];int32_t pan_x,pan_y;
    bool active,ready,pending,io_open,job_album,view_loaded,frame_valid,frame_complete,rendering,redraw,slide,slide_armed,resume_pending,jpeg_mode,stepping,album_known;
    int error;
} p;
#if !defined(LINNET_PROFILE_RELEASE)
static struct {uint32_t view_started,frame_ready,io_started,max_open_us,max_read_us,render_us,jpeg_us;} timing;
#define PHOTO_DIAG(code) do {code;} while(0)
#define PHOTO_START() uint32_t started=ln_time_us()
#else
#define PHOTO_DIAG(code) do {} while(0)
#define PHOTO_START() do {} while(0)
#endif
static const char package[]="/.LINNET/PHOTOS/LIBRARY.PIM";
static void clear(void*v,uint32_t n){
#if defined(__arm__)
    extern void ln_memory_clear(void *,uint32_t);ln_memory_clear(v,n);
#else
    uint8_t*b=v;while(n--)*b++=0;
#endif
}
static void copy(void*d,const void*s,uint32_t n){uint8_t*a=d;const uint8_t*b=s;while(n--)*a++=*b++;}
static void text(char*d,const char*s){uint32_t i=0;while(i<191&&s[i]){d[i]=s[i];++i;}d[i]=0;}
static uint32_t next_generation(void){if(++p.generation>=0x70000000u)p.generation=0x60000001u;return p.generation;}
static bool allowed(void){
    struct ln_player_status player;struct ln_audio_status audio;ln_player_snapshot(&player);ln_audio_snapshot(&audio);
    if(player.phase==LN_PLAYER_IDLE||player.phase==LN_PLAYER_ERROR||player.phase==LN_PLAYER_PAUSE)return true;
    uint32_t reserve=ln_player_background_frames(audio.rate);
    /* Verified PIMG record/thumbnail/tile requests are capped at 8 KiB.
     * Keep 500 ms (and the existing 8192-frame floor) for those bounded reads;
     * catalog opening/verification and JPEG retain the larger reserve. */
    if(p.ready&&!p.jpeg_mode&&p.phase>=RECORD&&p.phase<=TILE_DATA){
        uint32_t prepared=audio.rate/2u;if(prepared<8192u)prepared=8192u;
        if(prepared<reserve)reserve=prepared;
    }
    return audio.playing&&!audio.paused&&audio.queued>=reserve&&!ln_player_prefetch_urgent();
}
static bool cached_metadata_work(void){
    return (p.phase==VERIFY&&p.verify_cached)||
        (p.metadata_valid&&(p.phase==RECORD||p.phase==TITLE||p.phase==LEVEL||p.phase==TILE_RECORD||p.phase==SOURCE));
}
/* Storage admission belongs to read_at/open_file. These bounded steps only
 * consume validated memory; waiting for disk runway here stalls each render
 * slice and even the publication of a frame whose tiles are already loaded. */
static bool memory_work(void){
    return cached_metadata_work()||p.phase==TILE_COMMIT||
        (p.phase==VERIFY&&p.verify_at==p.header.data_at)||
        (p.phase==TILE_RECORD&&p.tile_records_count&&p.tile_index>=p.tile_records_first&&
         p.tile_index-p.tile_records_first<p.tile_records_count)||
        (p.phase==IDLE&&(p.resume_pending||
         (p.view==LN_PHOTOS_VIEWER&&p.view_loaded&&!p.jpeg_mode&&
          (p.rendering||p.redraw||!p.frame_complete))));
}
static void change(void){++p.epoch;++p.revision;}
static void fail(int error){p.error=error;p.phase=IDLE;p.rendering=false;p.slide=false;++p.revision;}
static int poll_file(struct ln_fat32_file *file,uint32_t *bytes){
    /* Drain a small burst of ready FAT/cache transitions before another full
     * decoder turn. Real hardware waits still return to the executive. */
    for(uint32_t step=0;step<4u;++step){
        int r=ln_storage_media_poll_deferred(p.generation,file,bytes);if(r)return r;
        uint32_t now=ln_time_us(),deadline;
        if(ln_storage_idle_wait(now,&deadline)&&(int32_t)(deadline-now)>0)return 0;
    }
    return 0;
}
/* Admission and completion remain in this phase until the exact request drains.
 * Bounded reads return to the executive; avoid recursive runtime work here. */
static int read_at(const struct ln_fat32_file*f,uint32_t at,void*buffer,uint32_t n){
    /* A verified small catalog remains in the unused frame workspace until
     * rendering reuses the surface. Browser record/title reads need no new storage owner. */
    if(!p.pending&&p.metadata_valid&&f==&p.file&&at>=512u&&at<=p.header.data_at&&n<=p.header.data_at-at){
        copy(buffer,p.surface.verify.metadata+at-512u,n);return 1;
    }
    if(!p.pending){if(!allowed())return 0;int r=ln_storage_media_read(f,at,buffer,n,next_generation());if(r<=0)return r;PHOTO_DIAG(timing.io_started=ln_time_us());p.pending=true;p.io_open=false;p.io_bytes=n;return 0;}
    uint32_t bytes=0;int r=poll_file(0,&bytes);if(!r)return 0;p.pending=false;
    PHOTO_DIAG(uint32_t elapsed=ln_time_us()-timing.io_started;if(elapsed>timing.max_read_us)timing.max_read_us=elapsed);
    if(p.working!=p.epoch)return 0;return r==1&&bytes==p.io_bytes?1:-1;
}
static int tile_record(void){
    if(p.tile_index>=p.header.tiles)return -1;
    if(!p.tile_records_count||p.tile_index<p.tile_records_first||p.tile_index-p.tile_records_first>=p.tile_records_count){
        uint32_t first=p.tile_index/64u*64u,count=p.header.tiles-first;if(count>64u)count=64u;
        /* A partial/canceled read must never publish a cache page. */
        p.tile_records_count=0;
        int r=read_at(&p.file,p.header.tile_at+first*8u,p.tile_records,count*8u);if(r<=0)return r;
        p.tile_records_first=first;p.tile_records_count=count;
    }
    uint32_t at;return ln_pimg_tile(&p.header,p.tile_records+(p.tile_index-p.tile_records_first)*8u,p.tile_index,&at,&p.tile_crc)?1:-1;
}
static int open_file(const char*path,struct ln_fat32_file*f){
    if(!p.pending){if(!allowed())return 0;int r=ln_storage_media_open(path,next_generation());if(r<=0)return r;PHOTO_DIAG(timing.io_started=ln_time_us());p.pending=p.io_open=true;return 0;}
    int r=poll_file(f,0);if(r)p.pending=false;
    if(r){PHOTO_DIAG(uint32_t elapsed=ln_time_us()-timing.io_started;if(elapsed>timing.max_open_us)timing.max_open_us=elapsed);}
    if(p.working!=p.epoch)return 0;return r;
}
static struct row *cached(uint32_t index,bool album){struct row*r=&p.rows[index%ROWS];return r->valid&&r->index==index&&r->album==album?r:0;}
static void begin_row(uint32_t index,bool album){p.job_index=index;p.job_slot=index%ROWS;p.job_album=album;p.rows[p.job_slot].valid=p.rows[p.job_slot].thumb=false;p.phase=RECORD;}
static bool path_safe(const uint8_t*s,uint32_t n){
    if(!ln_pimg_text(s,n,true)||n<5||s[n-4]!='.'||s[n-3]!='J'||s[n-2]!='P'||s[n-1]!='G')return false;
    uint32_t component=0,dots=0,extension=0;
    for(uint32_t i=1;i<=n;i++){uint32_t c=s[i];if(!c||c=='/'){if(!component||component>12||dots>1||(dots&&(!extension||extension>3)))return false;component=dots=extension=0;}
        else {++component;if(c=='.'){if(component==1||component>9)return false;++dots;}else {if(!((c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'))return false;if(dots)++extension;else if(component>8)return false;}}}
    return true;
}
static int string_read(uint32_t at,uint32_t bytes,bool path){
    uint32_t skip=at?1u:0u;int r=read_at(&p.file,p.header.string_at+at-skip,p.scratch,bytes+skip+1u);if(r!=1)return r;
    if((skip&&p.scratch[0])||!ln_pimg_text(p.scratch+skip,bytes,false)||(path&&!path_safe(p.scratch+skip,bytes)))return -2;
    if(skip)for(uint32_t i=0;i<=bytes;i++)p.scratch[i]=p.scratch[i+1];return 1;
}
static bool verify_bytes(uint32_t at,const uint8_t*b,uint32_t n){
    const struct ln_pimg_header*h=&p.header;
    /* Tile descriptors carry no per-record CRC; once a read contains only
     * aligned complete descriptors, validate them in place. The caller still
     * performs the same metadata CRC over every byte, while split/partial
     * records retain the existing scratch-buffer path. */
    if(at>=h->tile_at&&at<=h->string_at&&n<=h->string_at-at&&
       (at-h->tile_at)%8u==0&&n%8u==0){
        uint32_t index=(at-h->tile_at)/8u;
        for(uint32_t i=0;i<n;i+=8u){uint32_t offset,crc;
            if(!ln_pimg_tile(h,b+i,index++,&offset,&crc))return false;
        }
        return true;
    }
    for(uint32_t i=0;i<n;i++,at++){
        if(at<h->string_at){uint32_t base,width;
            if(at<h->photo_at){base=h->album_at;width=32;}else if(at<h->level_at){base=h->photo_at;width=64;}else if(at<h->tile_at){base=h->level_at;width=24;}else{base=h->tile_at;width=8;}
            /* Metadata chunks can split a record. Compute its position once
             * per fragment, keeping the same record validation at its end. */
            uint32_t offset=(at-base)%width,index=(at-base)/width,take=width-offset;
            if(take>n-i)take=n-i;
            for(uint32_t k=0;k<take;k++)p.verify_record[offset+k]=b[i+k];
            i+=take-1u;at+=take-1u;if(offset+take!=width)continue;
            if(width==32){struct ln_pimg_album a;if(!ln_pimg_album(h,p.verify_record,index,&a)||a.first!=p.v_photos)return false;p.v_photos+=a.count;p.surface.verify.album_counts[index]=a.count;}
            else if(width==64){struct ln_pimg_photo photo;if(!ln_pimg_photo(h,p.verify_record,index,&photo)||photo.first!=p.v_levels)return false;
                while(p.v_album<h->albums&&!p.surface.verify.album_counts[p.v_album])++p.v_album;
                if(p.v_album>=h->albums||photo.album!=p.v_album)return false;--p.surface.verify.album_counts[p.v_album];p.v_levels+=photo.levels;
                p.pixels.photo_info[index]=(photo.width-1u)|((photo.height-1u)<<14)|((photo.levels-1u)<<28);}
            else if(width==24){struct ln_pimg_level l;if(!ln_pimg_level(h,p.verify_record,index,&l)||l.photo!=p.v_photo||l.first!=p.v_tiles||p.v_photo>=h->photos)return false;
                uint32_t info=p.pixels.photo_info[p.v_photo],w=(info&16383u)+1u,height=((info>>14)&16383u)+1u,levels=(info>>28)+1u;
                if(l.width>w||l.height>height||(!p.v_level&&(l.width>WIDTH||l.height>HEIGHT))||(p.v_level&&(l.width<p.v_width||l.height<p.v_height||(l.width==p.v_width&&l.height==p.v_height))))return false;
                p.v_width=l.width;p.v_height=l.height;p.v_tiles+=l.count;if(++p.v_level==levels){++p.v_photo;p.v_level=0;}}
            else {uint32_t offset,crc;if(!ln_pimg_tile(h,p.verify_record,index,&offset,&crc))return false;}
        }else if(at<h->string_at+h->string_bytes){uint32_t c=b[i];
            if(at==h->string_at&&c)return false;
            if(!c){if(p.v_more)return false;p.v_text_bytes=0;continue;}
            if(++p.v_text_bytes>191||c<32||c==127)return false;
            if(p.v_more){if((c&0xc0u)!=0x80u)return false;p.v_code=(p.v_code<<6)|(c&63u);if(!--p.v_more&&(p.v_code<p.v_min||p.v_code>0x10ffffu||(p.v_code>=0xd800u&&p.v_code<=0xdfffu)))return false;}
            else if(c>=128){if(c>=0xc2&&c<=0xdf){p.v_more=1;p.v_code=c&31u;p.v_min=0x80;}else if(c>=0xe0&&c<=0xef){p.v_more=2;p.v_code=c&15u;p.v_min=0x800;}else if(c>=0xf0&&c<=0xf4){p.v_more=3;p.v_code=c&7u;p.v_min=0x10000;}else return false;}
        }else if(b[i])return false;
    }return true;
}
static int tile_find(uint32_t index){
    /* A hint is never proof: eviction, JPEG reuse and hash collisions all
     * fall back to the authoritative valid/index pair before touching pixels. */
    uint32_t bucket=index&(TILES-1u),slot=p.tile_hints[bucket];
    if(p.tiles[slot].valid&&p.tiles[slot].index==index)return (int)slot;
    for(uint32_t i=0;i<TILES;i++)if(p.tiles[i].valid&&p.tiles[i].index==index){p.tile_hints[bucket]=(uint8_t)i;return (int)i;}
    return -1;
}
static bool is_visible(uint32_t index){for(uint32_t i=0;i<p.visible_count;i++)if(p.visible[i]==index)return true;return false;}
static uint32_t victim(void){uint32_t best=UINT32_MAX,age=UINT32_MAX;for(uint32_t i=0;i<TILES;i++){if(!p.tiles[i].valid)return i;if(!is_visible(p.tiles[i].index)&&p.tiles[i].age<age){best=i;age=p.tiles[i].age;}}return best;}
static void source_xy(int32_t rx,int32_t ry,int32_t*sx,int32_t*sy){
    const struct ln_pimg_level*l=&p.levels[p.level];
    switch(p.rotation&3u){case 0:*sx=rx;*sy=ry;break;case 1:*sx=ry;*sy=(int32_t)l->height-1-rx;break;
    case 2:*sx=(int32_t)l->width-1-rx;*sy=(int32_t)l->height-1-ry;break;default:*sx=(int32_t)l->width-1-ry;*sy=rx;break;}
}
static void layout(void){
    if(!p.view_loaded||p.jpeg_mode)return;p.level=p.zoom<p.photo.levels?p.zoom:p.photo.levels-1u;
    const struct ln_pimg_level*l=&p.levels[p.level];uint32_t w=(p.rotation&1u)?l->height:l->width,h=(p.rotation&1u)?l->width:l->height;
    uint32_t dw=w,dh=h;if(!p.zoom){if(w*HEIGHT>h*WIDTH){dw=WIDTH;dh=h*WIDTH/w;}else{dh=HEIGHT;dw=w*HEIGHT/h;}if(!dw)dw=1;if(!dh)dh=1;}
    if(p.pan_x>(int32_t)w/2)p.pan_x=(int32_t)w/2;if(p.pan_x<-(int32_t)w/2)p.pan_x=-(int32_t)w/2;
    if(p.pan_y>(int32_t)h/2)p.pan_y=(int32_t)h/2;if(p.pan_y<-(int32_t)h/2)p.pan_y=-(int32_t)h/2;
    for(uint32_t x=0;x<WIDTH;x++){int32_t v=(int32_t)x-((int32_t)WIDTH-(int32_t)dw)/2;p.map_x[x]=v<0||v>=(int32_t)dw?-1:(int16_t)((uint32_t)v*w/dw);if(p.zoom)p.map_x[x]=(int16_t)((int32_t)x-(int32_t)WIDTH/2+(int32_t)w/2+p.pan_x);}
    for(uint32_t y=0;y<HEIGHT;y++){int32_t v=(int32_t)y-((int32_t)HEIGHT-(int32_t)dh)/2;p.map_y[y]=v<0||v>=(int32_t)dh?-1:(int16_t)((uint32_t)v*h/dh);if(p.zoom)p.map_y[y]=(int16_t)((int32_t)y-(int32_t)HEIGHT/2+(int32_t)h/2+p.pan_y);}
    p.visible_count=0;
    /* Source ranges are separable under quarter-turns; inspect boundaries at
     * tile crossings through the small display grid, never the whole image. */
    int32_t minx=2048,miny=2048,maxx=-1,maxy=-1;
    for(uint32_t x=0;x<WIDTH;x++)for(uint32_t y=0;y<HEIGHT;y+=HEIGHT-1u){int32_t sx,sy;source_xy(p.map_x[x],p.map_y[y],&sx,&sy);if(sx>=0&&sx<(int32_t)l->width){if(sx<minx)minx=sx;if(sx>maxx)maxx=sx;}}
    for(uint32_t y=0;y<HEIGHT;y++)for(uint32_t x=0;x<WIDTH;x+=WIDTH-1u){int32_t sx,sy;source_xy(p.map_x[x],p.map_y[y],&sx,&sy);if(sy>=0&&sy<(int32_t)l->height){if(sy<miny)miny=sy;if(sy>maxy)maxy=sy;}}
    /* Rotated axes may have margins at both sampled edges. Compute extrema
     * using each independent coordinate as well. */
    if(p.rotation&1u){minx=miny=2048;maxx=maxy=-1;
        for(uint32_t y=0;y<HEIGHT;y++){int32_t sx,sy;source_xy(0,p.map_y[y],&sx,&sy);if(sx>=0&&sx<(int32_t)l->width){if(sx<minx)minx=sx;if(sx>maxx)maxx=sx;}}
        for(uint32_t x=0;x<WIDTH;x++){int32_t sx,sy;source_xy(p.map_x[x],0,&sx,&sy);if(sy>=0&&sy<(int32_t)l->height){if(sy<miny)miny=sy;if(sy>maxy)maxy=sy;}}}
    if(maxx>=minx&&maxy>=miny)for(uint32_t y=(uint32_t)miny/32u;y<=(uint32_t)maxy/32u;y++)for(uint32_t x=(uint32_t)minx/32u;x<=(uint32_t)maxx/32u;x++){
        if(p.visible_count==TILES){fail(20);return;}p.visible[p.visible_count++]=l->first+y*l->columns+x;}
    p.redraw=false;p.rendering=false;p.frame_complete=false;p.ready_tiles=0;
}
static void slide_ready(void){
    if(p.slide&&!p.slide_armed){p.slide_at=ln_time_us()+5000000u;p.slide_armed=true;}
}
static void render_step(void){
    p.metadata_valid=false;
    PHOTO_START();
    if(!p.rendering){p.rendering=true;p.render_y=0;p.redraw=false;}
    const struct ln_pimg_level*l=&p.levels[p.level];uint16_t*out=p.surface.frame[p.front^1u];
    uint32_t end=p.render_y+8u;if(end>HEIGHT)end=HEIGHT;
    for(uint32_t y=p.render_y;y<end;y++){uint32_t last=UINT32_MAX;int slot=-1;
        /* Quarter-turn transforms are affine in x. Hoist the transform and
         * level geometry out of the pixel loop without changing scaled maps. */
        int32_t origin_x,origin_y,step_x,step_y;
        source_xy(0,p.map_y[y],&origin_x,&origin_y);source_xy(1,p.map_y[y],&step_x,&step_y);
        step_x-=origin_x;step_y-=origin_y;
        for(uint32_t x=0;x<WIDTH;x++){int32_t sx=origin_x+p.map_x[x]*step_x,sy=origin_y+p.map_x[x]*step_y;uint16_t color=0;
            if(p.map_x[x]>=0&&p.map_y[y]>=0&&sx>=0&&sy>=0&&sx<(int32_t)l->width&&sy<(int32_t)l->height){uint32_t tile=l->first+(uint32_t)sy/32u*l->columns+(uint32_t)sx/32u;
                if(tile!=last){last=tile;slot=tile_find(tile);}if(slot>=0)color=p.pixels.pimg.tiles[slot][((uint32_t)sy&31u)*32u+((uint32_t)sx&31u)];}
            out[y*WIDTH+x]=color;}}
    p.render_y=end;if(end==HEIGHT){p.front^=1u;p.asset.pixels=p.surface.frame[p.front];p.frame_valid=true;p.rendering=false;PHOTO_DIAG(timing.frame_ready=ln_time_us());slide_ready();++p.revision;}
    PHOTO_DIAG(timing.render_us+=ln_time_us()-started);
}
static void begin_view(uint32_t index){PHOTO_DIAG(timing.view_started=ln_time_us();timing.frame_ready=timing.render_us=timing.jpeg_us=0);p.slide_armed=false;p.photo_index=index;p.view=LN_PHOTOS_VIEWER;p.view_loaded=p.frame_valid=p.frame_complete=p.jpeg_mode=p.rendering=false;p.error=0;p.zoom=p.rotation=0;p.pan_x=p.pan_y=0;p.level_count=0;change();++p.navigation;}
void ln_photos_init(void){PHOTO_DIAG(clear(&timing,sizeof timing));clear(&p,sizeof p);p.generation=0x60000000u;p.phase=OPEN;p.window_count=ROWS;p.asset=(struct ln_ui_asset){WIDTH,HEIGHT,p.surface.frame[0]};}
void ln_photos_open(void){if(!p.active){p.active=true;p.error=0;change();++p.navigation;}}
void ln_photos_close(void){p.active=false;p.slide=false;change();}
bool ln_photos_active(void){return p.active;}
bool ln_photos_pending(void){return p.pending;}
#if !defined(LINNET_PROFILE_RELEASE)
void ln_photos_diagnostics(uint32_t out[32]){
    const uint32_t values[32]={0x544f4850u,0,p.phase,(uint32_t)p.error,p.active,p.ready,p.pending,p.view,
        p.file.size,p.verify_at,p.header.data_at,p.verify_crc,p.header.metadata_crc,p.v_photos,p.v_levels,p.v_tiles,
        p.photo_index,p.visible_count,p.revision,p.navigation,
        p.frame_valid,p.frame_complete,p.slide_armed,p.slide_at,ln_time_us(),timing.view_started,timing.frame_ready,
        timing.io_started,timing.max_open_us,timing.max_read_us,timing.render_us,timing.jpeg_us};
    for(uint32_t i=0;i<32u;++i)out[i]=values[i];
}
#endif
uint32_t ln_photos_view(void){return p.view;}
uint32_t ln_photos_count(void){return !p.ready?1u:p.view==LN_PHOTOS_ALBUMS?p.header.albums:p.view==LN_PHOTOS_LIST?p.count:0u;}
const char *ln_photos_label(uint32_t row){if(!p.ready)return p.error?"Photos unavailable":"Loading photos...";uint32_t index=p.view==LN_PHOTOS_ALBUMS?row:p.first+row;struct row*r=cached(index,p.view==LN_PHOTOS_ALBUMS);return r?r->title:"Loading...";}
void ln_photos_window(uint32_t first,uint32_t count){if(count>ROWS)count=ROWS;if(p.window_first==first&&p.window_count==count)return;p.window_first=first;p.window_count=count;change();}
const struct ln_ui_asset *ln_photos_thumbnail(uint32_t row){if(!p.ready||p.view!=LN_PHOTOS_LIST||row>=p.count||p.jpeg_mode)return 0;struct row*r=cached(p.first+row,false);return r&&r->thumb?&r->asset:0;}
const struct ln_ui_asset *ln_photos_asset(void){return p.view==LN_PHOTOS_VIEWER&&p.frame_valid?&p.asset:0;}
bool ln_photos_select(uint32_t row){
    if(!p.ready||row>=ln_photos_count())return false;struct row*r=cached(p.view==LN_PHOTOS_ALBUMS?row:p.first+row,p.view==LN_PHOTOS_ALBUMS);if(!r)return false;
    p.resume_pending=false;
    if(p.view==LN_PHOTOS_ALBUMS){p.album=row;p.first=r->data.a.first;p.count=r->data.a.count;p.photo_index=p.first;text(p.album_title,r->title);p.album_known=true;p.view=LN_PHOTOS_LIST;p.window_first=0;p.error=0;change();++p.navigation;}
    else if(p.view==LN_PHOTOS_LIST)begin_view(p.first+row);return true;
}
bool ln_photos_back(void){p.resume_pending=false;if(p.view==LN_PHOTOS_VIEWER){p.view=LN_PHOTOS_LIST;p.slide=p.jpeg_mode=false;p.error=0;p.window_first=(p.photo_index-p.first)/ROWS*ROWS;change();++p.navigation;return true;}if(p.view==LN_PHOTOS_LIST){p.view=LN_PHOTOS_ALBUMS;p.error=0;p.window_first=p.album/ROWS*ROWS;change();++p.navigation;return true;}ln_photos_close();return false;}
void ln_photos_next(int direction){if(p.view!=LN_PHOTOS_VIEWER||!p.count)return;uint32_t i=p.photo_index-p.first;if(direction<0)i=i?i-1:p.count-1;else i=i+1==p.count?0:i+1;bool slide=p.slide;begin_view(p.first+i);p.slide=slide;}
void ln_photos_zoom(int direction){if(!p.view_loaded||p.jpeg_mode)return;uint32_t z=p.zoom,max=p.photo.levels-1u;
    if(direction>0){uint32_t delta=(uint32_t)direction;z+=delta>max-z?max-z:delta;}
    else if(direction<0)z=direction<-(int)z?0u:(uint32_t)((int)z+direction);
    if(z!=p.zoom){p.zoom=z;p.pan_x=p.pan_y=0;change();layout();}}
void ln_photos_pan(int dx,int dy){if(!p.view_loaded||!p.zoom||p.jpeg_mode)return;p.pan_x+=dx;p.pan_y+=dy;change();layout();}
void ln_photos_rotate(void){if(!p.view_loaded||p.jpeg_mode)return;p.rotation=(p.rotation+1u)&3u;p.pan_x=p.pan_y=0;change();layout();}
void ln_photos_slideshow(bool enabled){p.slide=enabled&&p.view==LN_PHOTOS_VIEWER;p.slide_armed=false;if(p.frame_valid)slide_ready();++p.revision;}
bool ln_photos_slideshow_active(void){return p.slide;}
uint32_t ln_photos_revision(void){return p.revision;}
uint32_t ln_photos_navigation(void){return p.navigation;}
uint32_t ln_photos_selection(void){return p.view==LN_PHOTOS_ALBUMS?(p.album<p.header.albums?p.album:0):p.view==LN_PHOTOS_LIST&&p.photo_index>=p.first&&p.photo_index-p.first<p.count?p.photo_index-p.first:0;}
const char *ln_photos_title(void){return p.view==LN_PHOTOS_ALBUMS?"Photo albums":p.view==LN_PHOTOS_LIST?p.album_title:p.title;}
const char *ln_photos_hint(void){return p.view==LN_PHOTOS_VIEWER?(p.slide?"Slideshow  Menu: Back":"Wheel: Zoom  Select: Controls"):"Select: Open  Menu: Back";}
const char *ln_photos_status(void){return p.error?"Image unavailable":!p.ready?"Loading catalog":p.jpeg_mode&&!p.frame_valid?"Decoding JPEG":p.view==LN_PHOTOS_VIEWER&&!p.frame_valid?"Loading image":"";}
void ln_photos_resume_get(uint8_t out[16]){
    if(p.resume_pending){copy(out,p.resume,16);return;}
    bool empty=p.ready&&p.album_known&&p.view!=LN_PHOTOS_VIEWER&&!p.count;
    ln_write_le32(out,p.ready?p.header.identity:0);ln_write_le32(out+4,empty?EMPTY_ALBUM_RESUME:p.photo_index);
    ln_write_le32(out+8,(empty?0:p.zoom|(p.rotation<<8))|(p.view<<16));
    ln_write_le32(out+12,empty?p.album:(uint16_t)p.pan_x|((uint32_t)(uint16_t)p.pan_y<<16));
}
bool ln_photos_resume_set(const uint8_t in[16]){
    uint32_t flags=ln_read_le32(in+8),index=ln_read_le32(in+4);
    if(index>EMPTY_ALBUM_RESUME||(flags&0xffu)>5||((flags>>8)&255u)>3||(flags>>16)>2)return false;
    if(index==EMPTY_ALBUM_RESUME&&((flags&65535u)||(flags>>16)==LN_PHOTOS_VIEWER||ln_read_le32(in+12)>=4096u))return false;
    copy(p.resume,in,16);p.resume_pending=true;p.resume_stage=0;return true;
}
static bool resume_matches(void){
    return ln_read_le32(p.resume)==p.header.identity&&(ln_read_le32(p.resume+4)==EMPTY_ALBUM_RESUME?
        ln_read_le32(p.resume+12)<p.header.albums:ln_read_le32(p.resume+4)<p.header.photos);
}
static void restore_resume(void){
    if(!resume_matches()){p.resume_pending=false;return;}
    uint32_t index=ln_read_le32(p.resume+4),view=ln_read_le32(p.resume+8)>>16;bool empty=index==EMPTY_ALBUM_RESUME;
    if(!p.resume_stage){
        if(empty)p.album=ln_read_le32(p.resume+12);
        else{struct row*row=cached(index,false);if(!row){begin_row(index,false);return;}p.album=row->data.p.album;}
        p.resume_stage=1;
    }
    struct row*a=cached(p.album,true);if(!a){begin_row(p.album,true);return;}
    p.first=a->data.a.first;p.count=a->data.a.count;text(p.album_title,a->title);p.album_known=true;
    if(empty?p.count!=0:index<p.first||index-p.first>=p.count){p.resume_pending=false;fail(17);return;}
    if(view!=LN_PHOTOS_VIEWER){
        p.view=view;p.photo_index=empty?p.first:index;
        p.window_first=view==LN_PHOTOS_LIST?(empty?0:(index-p.first)/ROWS*ROWS):p.album/ROWS*ROWS;
        p.resume_pending=false;++p.navigation;++p.revision;return;
    }
    begin_view(index);
}
/* Inspect at most ROWS cached entries, or one unloaded viewer row. Planning
 * never submits I/O; the selected phase retains the normal admission gate. */
static bool plan_content(bool apply){
    if(p.view==LN_PHOTOS_VIEWER){
        if(p.view_loaded)return false;
        struct row*row=cached(p.photo_index,false);if(!apply)return true;
        if(!row){begin_row(p.photo_index,false);return true;}
        if(row->data.p.album!=p.album||p.photo_index<p.first||p.photo_index-p.first>=p.count){fail(18);return true;}
        p.photo=row->data.p;text(p.title,row->title);p.level_count=0;p.phase=LEVEL;return true;
    }
    uint32_t count=ln_photos_count();
    for(uint32_t i=0;i<p.window_count&&i<ROWS&&p.window_first+i<count;i++){
        uint32_t index=p.view==LN_PHOTOS_ALBUMS?p.window_first+i:p.first+p.window_first+i;
        struct row*row=cached(index,p.view==LN_PHOTOS_ALBUMS);
        if(!row){if(apply)begin_row(index,p.view==LN_PHOTOS_ALBUMS);return true;}
        if(p.view==LN_PHOTOS_LIST&&!row->thumb){if(apply){p.job_slot=index%ROWS;p.phase=THUMB;}return true;}
    }
    return false;
}
static bool idle_plan(bool apply){
    if(!p.active||!p.ready||p.error||p.pending||p.phase!=IDLE||p.working!=p.epoch||
       (p.resume_pending&&p.view!=LN_PHOTOS_VIEWER))return false;
    return plan_content(apply);
}
bool ln_photos_busy(void){
    return p.active&&!p.error&&(!p.ready||p.pending||p.working!=p.epoch||
        p.phase!=IDLE||p.resume_pending||plan_content(false)||
        (p.view==LN_PHOTOS_VIEWER&&(!p.frame_valid||p.rendering||p.redraw||
         (!p.jpeg_mode&&!p.frame_complete))));
}
uint32_t ln_photos_deadline(uint32_t now){if(p.pending)return now;if(!p.active||p.error)return now+200000u;if(idle_plan(false)||memory_work())return now;if(!allowed())return now+200000u;if(p.phase!=IDLE||p.rendering||p.redraw||(p.view==LN_PHOTOS_VIEWER&&!p.jpeg_mode&&!p.frame_complete))return now;if(p.slide&&p.slide_armed&&(int32_t)(p.slide_at-now)>0)return p.slide_at;return now+200000u;}
static void image_fail(int error){
    if(p.photo.source_bytes&&!p.jpeg_mode){p.phase=SOURCE;p.rendering=false;p.frame_valid=false;return;}fail(error);
}
static void photo_step(void){
    if(p.working!=p.epoch){
        if(p.pending){ln_storage_media_cancel(p.generation);if(!ln_storage_media_poll(p.generation,0,0))return;p.pending=false;}
        p.working=p.epoch;p.phase=p.ready?IDLE:OPEN;if(p.rendering&&!p.jpeg_mode)p.redraw=true;p.rendering=false;
        if(p.jpeg_mode&&!p.frame_valid){p.jpeg_mode=false;p.view_loaded=false;}
    }
    if(!p.active)return;
    if(p.slide&&p.slide_armed&&p.frame_valid&&(int32_t)(ln_time_us()-p.slide_at)>=0){ln_photos_next(1);return;}
    if(idle_plan(true))return;
    if(!p.pending&&!memory_work()&&!allowed())return;
    int r;
    if(p.phase==OPEN){r=open_file(package,&p.file);if(!r)return;if(r<0){fail(1);return;}p.phase=HEADER;return;}
    if(p.phase==HEADER){r=read_at(&p.file,0,p.scratch,512);if(!r)return;if(r<0||!ln_pimg_header(p.scratch,p.file.size,&p.header)){fail(2);return;}p.metadata_valid=false;p.tile_records_count=0;p.verify_cached=p.verify_cursor=0;p.verify_at=512;p.verify_crc=UINT32_MAX;p.v_photos=p.v_levels=p.v_tiles=p.v_album=p.v_photo=p.v_level=p.v_width=p.v_height=p.v_text_bytes=p.v_more=p.v_code=p.v_min=0;p.phase=VERIFY;return;}
    if(p.phase==VERIFY){
        /* Frame surfaces are unused until catalog verification completes.
         * Coalesce repeated chain proofs without borrowing photo_info or album
         * counts. Admission keeps the audio reserve; CPU validation stays 4 KB. */
        uint32_t left=p.header.data_at-p.verify_at;
        if(left){
            if(!p.verify_cached){
                uint32_t bytes=left;if(bytes>16384u)bytes=16384u;
                uint32_t at=p.header.data_at-512u<=sizeof p.surface.verify.metadata?p.verify_at-512u:0u;
                r=read_at(&p.file,p.verify_at,p.surface.verify.metadata+at,bytes);
                if(!r)return;if(r<0){fail(3);return;}
                p.verify_cached=bytes;p.verify_cursor=at;
            }
            uint32_t n=p.verify_cached;if(n>4096)n=4096;
            const uint8_t *bytes=p.surface.verify.metadata+p.verify_cursor;
            if(!verify_bytes(p.verify_at,bytes,n)){fail(4);return;}
            p.verify_crc=ln_pimg_crc_update(p.verify_crc,bytes,n);
            p.verify_at+=n;p.verify_cursor+=n;p.verify_cached-=n;return;
        }
        if((p.verify_crc^UINT32_MAX)!=p.header.metadata_crc||p.v_photos!=p.header.photos||p.v_levels!=p.header.levels||p.v_tiles!=p.header.tiles||p.v_photo!=p.header.photos||p.v_text_bytes||p.v_more){fail(5);return;}p.metadata_valid=p.header.data_at-512u<=sizeof p.surface.verify.metadata;p.ready=true;p.phase=IDLE;++p.revision;
        if(p.resume_pending&&!resume_matches())p.resume_pending=false;return;
    }
    if(p.phase==RECORD){
        uint32_t size=p.job_album?32u:64u,at=(p.job_album?p.header.album_at:p.header.photo_at)+p.job_index*size;
        r=read_at(&p.file,at,p.scratch,size);if(!r)return;struct row*row=&p.rows[p.job_slot];
        bool valid=r>0&&(p.job_album?ln_pimg_album(&p.header,p.scratch,p.job_index,&row->data.a):ln_pimg_photo(&p.header,p.scratch,p.job_index,&row->data.p));
        if(!valid){fail(6);return;}row->index=p.job_index;row->album=p.job_album;p.phase=TITLE;return;
    }
    if(p.phase==TITLE){struct row*row=&p.rows[p.job_slot];r=string_read(row->album?row->data.a.title:row->data.p.title,row->album?row->data.a.bytes:row->data.p.bytes,false);
        if(!r)return;if(r<0){fail(7);return;}text(row->title,(char*)p.scratch);row->valid=true;row->asset=(struct ln_ui_asset){64,64,p.pixels.pimg.thumbs[p.job_slot]};p.phase=IDLE;++p.revision;return;}
    if(p.phase==THUMB){struct row*row=&p.rows[p.job_slot];r=read_at(&p.file,row->data.p.thumb,p.pixels.pimg.thumbs[p.job_slot],8192);
        if(!r)return;if(r<0||ln_crc32((uint8_t*)p.pixels.pimg.thumbs[p.job_slot],8192)!=row->data.p.thumb_crc){fail(8);return;}row->thumb=true;p.phase=IDLE;++p.revision;return;}
    if(p.phase==LEVEL){
        /* Descriptors are contiguous; retain the same request until it drains. */
        if(!p.photo.levels||p.photo.levels>6u||p.photo.first>p.header.levels||p.photo.levels>p.header.levels-p.photo.first){image_fail(9);return;}
        r=read_at(&p.file,p.header.level_at+p.photo.first*24u,p.scratch,p.photo.levels*24u);if(!r)return;
        if(r<0){image_fail(9);return;}
        for(p.level_count=0;p.level_count<p.photo.levels;++p.level_count){
        struct ln_pimg_level*l=&p.levels[p.level_count];
        if(!ln_pimg_level(&p.header,p.scratch+p.level_count*24u,p.photo.first+p.level_count,l)||l->photo!=p.photo_index||
           l->width>p.photo.width||l->height>p.photo.height||(!p.level_count&&(l->width>WIDTH||l->height>HEIGHT))||
           (p.level_count&&(l->width<p.levels[p.level_count-1].width||l->height<p.levels[p.level_count-1].height||(l->width==p.levels[p.level_count-1].width&&l->height==p.levels[p.level_count-1].height)||l->first!=p.levels[p.level_count-1].first+p.levels[p.level_count-1].count))){image_fail(9);return;}
        }
        p.view_loaded=true;p.phase=IDLE;
        if(p.resume_pending&&p.photo_index==ln_read_le32(p.resume+4)){uint32_t flags=ln_read_le32(p.resume+8),pan=ln_read_le32(p.resume+12);p.zoom=flags&255u;p.rotation=(flags>>8)&3u;p.pan_x=(int16_t)pan;p.pan_y=(int16_t)(pan>>16);p.resume_pending=false;}
        if(p.zoom>=p.photo.levels)p.zoom=p.photo.levels-1u;layout();return;
    }
    if(p.phase==TILE_RECORD){r=tile_record();if(!r)return;
        if(r<0){image_fail(10);return;}
        /* Adjacent visible tiles share one read, using the existing scratch
         * buffer. Stop at the level/page boundary and never fetch hidden tiles. */
        const struct ln_pimg_level*l=&p.levels[p.level];p.tile_group_count=1;
        while(p.tile_group_count<sizeof p.scratch/2048u){
            uint32_t index=p.tile_index+p.tile_group_count;
            if(index>=p.header.tiles||index-l->first>=l->count||
               index-p.tile_records_first>=p.tile_records_count||
               !is_visible(index)||tile_find(index)>=0)break;
            uint32_t at,crc;
            if(!ln_pimg_tile(&p.header,p.tile_records+(index-p.tile_records_first)*8u,index,&at,&crc)){image_fail(10);return;}
            ++p.tile_group_count;
        }
        p.tile_group_cursor=0;p.phase=TILE_DATA;return;}
    if(p.phase==TILE_DATA){r=read_at(&p.file,p.header.data_at+p.header.photos*8192u+p.tile_index*2048u,p.scratch,p.tile_group_count*2048u);if(!r)return;
        if(r<0){image_fail(11);return;}p.phase=TILE_COMMIT;return;}
    if(p.phase==TILE_COMMIT){
        uint32_t index=p.tile_index+p.tile_group_cursor,at,crc;
        const uint8_t*bytes=p.scratch+p.tile_group_cursor*2048u;
        if(!ln_pimg_tile(&p.header,p.tile_records+(index-p.tile_records_first)*8u,index,&at,&crc)||ln_crc32(bytes,2048)!=crc){image_fail(11);return;}
        p.tile_slot=victim();if(p.tile_slot==UINT32_MAX){fail(19);return;}
        p.tiles[p.tile_slot].valid=false;copy(p.pixels.pimg.tiles[p.tile_slot],bytes,2048);
        const struct ln_pimg_level*l=&p.levels[p.level];uint32_t local=index-l->first,tx=local%l->columns*32u,ty=local/l->columns*32u;
        /* Interior tiles have no padding; edge tiles inspect only padding.
         * The full payload CRC above still covers every pixel. */
        if(tx+32u>l->width||ty+32u>l->height){
            uint32_t used_x=l->width-tx,used_y=l->height-ty;if(used_x>32u)used_x=32u;
            for(uint32_t y=0;y<32u;y++)for(uint32_t x=y<used_y?used_x:0u;x<32u;x++)
                if(p.pixels.pimg.tiles[p.tile_slot][y*32u+x]){image_fail(21);return;}
        }
        p.tiles[p.tile_slot]=(struct tile){index,++p.age,true};++p.ready_tiles;
        if(++p.tile_group_cursor==p.tile_group_count)p.phase=IDLE;return;}
    if(p.phase==SOURCE){r=string_read(p.photo.source,p.photo.source_bytes,true);if(!r)return;if(r<0){fail(12);return;}copy(p.source,p.scratch,p.photo.source_bytes+1u);p.jpeg_mode=true;p.frame_valid=false;p.redraw=p.rendering=false;
        for(uint32_t i=0;i<ROWS;i++)p.rows[i].thumb=false;for(uint32_t i=0;i<TILES;i++)p.tiles[i].valid=false;p.phase=JPEG_OPEN;return;}
    if(p.phase==JPEG_OPEN){p.metadata_valid=false;r=open_file(p.source,&p.jpeg_file);if(!r)return;if(r<0||p.jpeg_file.size!=p.photo.jpeg_bytes){fail(13);return;}p.jpeg_at=0;p.jpeg_crc=UINT32_MAX;p.phase=JPEG_LOAD;return;}
    if(p.phase==JPEG_LOAD){uint32_t n=p.photo.jpeg_bytes-p.jpeg_at;if(n>4096)n=4096;
        if(n){r=read_at(&p.jpeg_file,p.jpeg_at,p.pixels.jpeg+p.jpeg_at,n);if(!r)return;if(r<0){fail(14);return;}p.jpeg_crc=ln_pimg_crc_update(p.jpeg_crc,p.pixels.jpeg+p.jpeg_at,n);p.jpeg_at+=n;return;}
        if((p.jpeg_crc^UINT32_MAX)!=p.photo.jpeg_crc||ln_photo_jpeg_init(&p.jpeg,p.pixels.jpeg,p.photo.jpeg_bytes,p.surface.frame[p.front^1u],WIDTH,HEIGHT,WIDTH,p.photo.orientation)<0){fail(15);return;}
        p.phase=JPEG_DECODE;return;}
    if(p.phase==JPEG_DECODE){PHOTO_START();r=ln_photo_jpeg_step(&p.jpeg);PHOTO_DIAG(timing.jpeg_us+=ln_time_us()-started);if(!r)return;uint32_t w=p.photo.orientation>=5?p.jpeg.height:p.jpeg.width,h=p.photo.orientation>=5?p.jpeg.width:p.jpeg.height;
        if(r<0||w!=p.photo.width||h!=p.photo.height){fail(16);return;}p.front^=1u;p.asset.pixels=p.surface.frame[p.front];p.frame_valid=p.view_loaded=true;p.phase=IDLE;PHOTO_DIAG(timing.frame_ready=ln_time_us());slide_ready();++p.revision;return;}
    if(p.error)return;
    if(p.resume_pending&&p.view!=LN_PHOTOS_VIEWER){
        restore_resume();return;
    }
    if(p.view!=LN_PHOTOS_VIEWER||!p.view_loaded){(void)plan_content(true);return;}
    if(p.view==LN_PHOTOS_VIEWER){
        if(p.jpeg_mode)return;
        if(p.rendering||p.redraw){render_step();return;}
        if(p.frame_complete)return;
        for(uint32_t i=0;i<p.visible_count;i++)if(tile_find(p.visible[i])<0){p.tile_slot=victim();if(p.tile_slot==UINT32_MAX){fail(19);return;}p.tile_index=p.visible[i];p.phase=TILE_RECORD;return;}
        p.frame_complete=true;p.ready_tiles=0;p.redraw=true;
        return;
    }
}
void ln_photos_step(void){
    /* Storage progress services the runtime, which may call us again while an
     * outer poll still owns its phase and buffer. Only that outer call advances. */
    if(p.stepping)return;p.stepping=true;photo_step();p.stepping=false;
}
