#include "browser.h"
#include "library.h"
#include "hal/api/platform.h"

enum view { CATEGORIES, GROUPS, TRACKS };
enum job { NONE, RANGE, GROUP, TITLE, PRELOAD, QUEUE_MEMBER };
/* Keep recently visited rows behind the viewport as well as lookahead.
 * Absolute row tags and dataset identity prevent reuse across collisions/views. */
#define FIRST_PAGE_ROWS 12u
#define ROW_CACHE (LN_MUSIC_BROWSER_ROWS*2u)
struct row { char label[256]; uint32_t index,count,ordinal; bool valid; };
static struct {
    struct row rows[ROW_CACHE],first_page[FIRST_PAGE_ROWS];
    bool labels_pending;
    uint32_t labels_started;
    uint32_t group_lower[8],group_count[8];
    bool group_range_ready[8];
    enum view view;
    enum job job;
    uint32_t kind,first,count,group,lower,lo,hi,mid,range_phase,visible_rows;
    uint32_t epoch,job_epoch,job_row,revision,selection,track,navigation;
    bool selecting,track_ready,was_ready,window_ready;
    bool suspended,search_ready;
    bool visible,cache_ready;
    enum view cache_view;
    uint32_t cache_kind,cache_group;
    char title[256];
    struct ln_music_browser_queue queue;
    uint32_t queue_next;int queue_status;bool single;
} browser;
static const char *const categories[]={"All Tracks","Artists","Albums","Genres",
    "Composers","Years","Folders","Playlists","Search"};
static void copy(char *out,const char *in)
{ uint32_t i=0;while(i<255u&&in[i]){out[i]=in[i];i++;}out[i]=0; }
static void changed(void){browser.revision++;}
static struct row *row_slot(uint32_t ordinal){return &browser.rows[ordinal%ROW_CACHE];}
static bool row_ready(uint32_t ordinal){
    struct row *r=row_slot(ordinal);return r->valid&&r->ordinal==ordinal;
}
static uint32_t lookahead(void){
    return browser.visible_rows>=LN_MUSIC_BROWSER_ROWS/2u?LN_MUSIC_BROWSER_ROWS:browser.visible_rows*2u;
}
static uint32_t preload_count(void){
    uint32_t count=browser.visible_rows<FIRST_PAGE_ROWS?browser.visible_rows:FIRST_PAGE_ROWS;
    return count<ln_music_library_count()?count:ln_music_library_count();
}
static void labels_changed(void){
    if(!browser.labels_pending)browser.labels_started=ln_time_us();
    browser.labels_pending=true;
}
void ln_music_browser_publish(void){
    if(!browser.labels_pending)return;
    bool complete=true;
    for(uint32_t i=0;i<browser.visible_rows&&browser.first+i<browser.count;i++)
        if(!row_ready(browser.first+i)){complete=false;break;}
    if(complete||(uint32_t)(ln_time_us()-browser.labels_started)>=50000u){
        browser.labels_pending=false;changed();
    }
}
static void invalidate(void)
{
    browser.epoch++;browser.selecting=false;browser.queue_status=LN_BROWSER_QUEUE_IDLE;browser.track_ready=false;browser.single=false;
    browser.window_ready=false;browser.labels_pending=false;
    /* Categories do not consume rows. Re-entering the same dataset can reuse
     * them; another group or a library reload must discard them. */
    if(browser.view!=CATEGORIES&&(!browser.cache_ready||browser.cache_view!=browser.view||
       browser.cache_kind!=browser.kind||(browser.view==TRACKS&&browser.kind&&browser.cache_group!=browser.group))){
        for(uint32_t i=0;i<ROW_CACHE;i++)browser.rows[i].valid=false;
        browser.cache_ready=true;browser.cache_view=browser.view;
        browser.cache_kind=browser.kind;browser.cache_group=browser.group;
    }
    if(browser.view==TRACKS&&!browser.kind){
        for(uint32_t i=0;i<FIRST_PAGE_ROWS;i++)
            if(browser.first_page[i].valid)*row_slot(i)=browser.first_page[i];
    }
    changed();
}
void ln_music_browser_suspend(bool suspend){browser.suspended=suspend;}
void ln_music_browser_set_visible(bool visible){browser.visible=visible;}
bool ln_music_browser_window_needed(void){
    /* Browsing uses title-only queries; full metadata is reserved for playback. */
    return false;
}
bool ln_music_browser_query_idle(void){return browser.job==NONE;}
bool ln_music_browser_take_search(void){bool result=browser.search_ready;browser.search_ready=false;return result;}
void ln_music_browser_init(void)
{
    unsigned char *p=(unsigned char *)&browser;
    for(uint32_t i=0;i<sizeof(browser);i++)p[i]=0;
    copy(browser.title,"Music");browser.revision=1;browser.visible=true;browser.visible_rows=12u;
}
uint32_t ln_music_browser_count(void)
{return browser.view==CATEGORIES?9u:browser.count;}
const char *ln_music_browser_title(void){
    if(browser.queue_status==LN_BROWSER_QUEUE_CAPACITY)return "Too many: Play for one";
    if(browser.queue_status==LN_BROWSER_QUEUE_INVALID)return "Cannot build queue";
    if(browser.queue_status==LN_BROWSER_QUEUE_LOADING)return "Preparing queue";
    return browser.title;
}
bool ln_music_browser_busy(void){
    if(!browser.was_ready)return false;
    if(browser.view==CATEGORIES){
        if(browser.job!=NONE)return true;
        if(browser.suspended||!browser.visible)return false;
        for(uint32_t i=0;i<preload_count();i++)if(!browser.first_page[i].valid)return true;
        return false;
    }
    if(browser.labels_pending)return true;
    if(browser.job!=NONE||browser.selecting||browser.queue_status==LN_BROWSER_QUEUE_LOADING)return true;
    if(browser.suspended||!browser.visible)return false;
    if(browser.range_phase)return true;
    if(browser.window_ready)return false;
    for(uint32_t i=0;i<lookahead()&&browser.first+i<browser.count;++i)
        if(!row_ready(browser.first+i))return true;
    return false;
}
uint32_t ln_music_browser_revision(void){return browser.revision;}
uint32_t ln_music_browser_navigation(void){return browser.navigation;}
const char *ln_music_browser_label(uint32_t row)
{
    if(row>=ln_music_browser_count())return "";
    if(browser.view==CATEGORIES)return categories[row];
    if(row<browser.first||row-browser.first>=LN_MUSIC_BROWSER_ROWS)return "Loading...";
    return row_ready(row)?row_slot(row)->label:"Loading...";
}
void ln_music_browser_visible_rows(uint32_t rows)
{ rows=rows?rows:1u;if(browser.visible_rows!=rows)browser.window_ready=false;browser.visible_rows=rows; }
void ln_music_browser_window(uint32_t first)
{
    if(browser.view==CATEGORIES||first==browser.first)return;
    if(!browser.count)first=0;
    else if(first>=browser.count)first=browser.count-1u;
    /* Moving the viewport changes only which cached rows providers expose.
     * Selection damage already repaints a new page; resolved rows publish
     * their own revisions, so a window move needs no redundant refresh. */
    browser.first=first;browser.selecting=false;browser.queue_status=LN_BROWSER_QUEUE_IDLE;
    browser.track_ready=false;browser.single=false;browser.window_ready=false;
}
static void groups(void)
{
    browser.navigation++;
    browser.view=GROUPS;browser.count=0;browser.first=0;
    browser.lo=0;browser.hi=ln_music_library_group_count();
    browser.range_phase=1;
    if(browser.group_range_ready[browser.kind]){
        browser.lower=browser.group_lower[browser.kind];
        browser.count=browser.group_count[browser.kind];browser.range_phase=0;
    }
    copy(browser.title,categories[browser.kind]);invalidate();
}
bool ln_music_browser_open_album(uint32_t group,uint32_t count,const char *title){
    if(!browser.was_ready||!count||group>=ln_music_library_group_count())return false;
    browser.kind=2;browser.group=group;browser.count=count;browser.view=TRACKS;browser.first=0;
    browser.range_phase=0;browser.navigation++;copy(browser.title,title);invalidate();return true;
}
bool ln_music_browser_select(uint32_t row)
{
    if(row>=ln_music_browser_count())return false;
    browser.track_ready=false;browser.queue_status=LN_BROWSER_QUEUE_IDLE;browser.single=false;++browser.epoch;
    if(browser.view==CATEGORIES){
        if(!browser.was_ready)return false;
        if(row==8u){browser.search_ready=true;changed();return true;}
        browser.kind=row;
        if(row)groups();
        else {browser.view=TRACKS;browser.count=ln_music_library_count();browser.first=0;
            browser.navigation++;
            copy(browser.title,categories[0]);invalidate();}
        return true;
    }
    if(row<browser.first||row-browser.first>=LN_MUSIC_BROWSER_ROWS)
        ln_music_browser_window(row);
    browser.selection=row;browser.selecting=true;
    return true;
}
bool ln_music_browser_select_single(uint32_t row)
{if(browser.view!=TRACKS||!ln_music_browser_select(row))return false;browser.single=true;return true;}
int ln_music_browser_queue_status(void){return browser.queue_status;}
bool ln_music_browser_take_queue(struct ln_music_browser_queue *out)
{if(!out||browser.queue_status!=LN_BROWSER_QUEUE_READY)return false;*out=browser.queue;
 browser.queue_status=LN_BROWSER_QUEUE_IDLE;browser.track_ready=false;return true;}
static void queue_publish(void)
{browser.queue_status=LN_BROWSER_QUEUE_READY;if(!browser.queue.source)browser.track=browser.queue.tracks[browser.queue.cursor];browser.track_ready=true;changed();}
static void queue_begin(uint32_t track)
{
    browser.queue=(struct ln_music_browser_queue){0};
    browser.queue.count=browser.single?1u:browser.count;
    browser.queue.cursor=browser.single?0u:browser.selection;

    if(!browser.queue.count||browser.queue.cursor>=browser.queue.count||!ln_music_library_identity(browser.queue.library_hash)){
        browser.queue_status=LN_BROWSER_QUEUE_INVALID;changed();return;}
    if(browser.queue.count>LINNET_QUEUE_SOURCE_MAX){browser.queue_status=LN_BROWSER_QUEUE_INVALID;changed();return;}
    if(!browser.single&&browser.queue.count>LINNET_QUEUE_CAPACITY){
        browser.queue.source=browser.kind?LN_QUEUE_GROUP:LN_QUEUE_ALL;browser.queue.source_group=browser.kind?browser.group:0;
        browser.track=track;queue_publish();return;
    }
    if(browser.single){browser.queue.tracks[0]=track;queue_publish();return;}
    if(!browser.kind){for(uint32_t i=0;i<browser.queue.count;++i)browser.queue.tracks[i]=i;queue_publish();return;}
    browser.queue_next=0;browser.queue_status=LN_BROWSER_QUEUE_LOADING;changed();
}
bool ln_music_browser_back(void)
{
    if(browser.view==CATEGORIES)return false;
    if(browser.view==TRACKS&&browser.kind)groups();
    else {browser.view=CATEGORIES;browser.first=0;browser.count=0;
        browser.navigation++;
        browser.range_phase=0;copy(browser.title,"Music");invalidate();}
    browser.track_ready=false;return true;
}
static void accept_selection(void)
{
    if(!browser.selecting||browser.selection<browser.first||
       browser.selection-browser.first>=LN_MUSIC_BROWSER_ROWS)return;
    struct row *r=row_slot(browser.selection);
    if(!row_ready(browser.selection))return;
    browser.selecting=false;
    if(browser.view==GROUPS){
        browser.group=r->index;browser.count=r->count;copy(browser.title,r->label);
        browser.navigation++;
        browser.view=TRACKS;browser.first=0;invalidate();
    }else if(browser.view==TRACKS)queue_begin(r->index);
}
void ln_music_browser_step(void)
{
    bool ready=ln_music_library_status()==LN_LIBRARY_READY;
    if(!ready){
        browser.cache_ready=false;browser.labels_pending=false;
        for(uint32_t i=0;i<FIRST_PAGE_ROWS;i++)browser.first_page[i].valid=false;
        for(uint32_t i=0;i<8u;i++)browser.group_range_ready[i]=false;
        if(browser.was_ready){
            browser.navigation++;
            browser.view=CATEGORIES;browser.first=0;browser.count=0;
            browser.range_phase=0;browser.track_ready=false;copy(browser.title,"Music");invalidate();
        }
        /* Library invalidates external queries on reload/cancel/error. */
        browser.job=NONE;browser.was_ready=false;return;
    }
    if(!browser.was_ready){browser.was_ready=true;changed();}
    if(browser.job!=NONE){
        struct ln_music_group g;char name[256];uint32_t track=UINT32_MAX;
        struct ln_music_library_search_row title;
        bool done=(browser.job==TITLE||browser.job==PRELOAD)?ln_music_library_take_view_row(&title):browser.job==QUEUE_MEMBER?ln_music_library_take_member(&track):
            ln_music_library_take_group(&g,name);
        if(!done)return;
        enum job completed=browser.job;browser.job=NONE;
        if(completed==PRELOAD){
            struct row *r=&browser.first_page[browser.job_row];
            *r=(struct row){.index=title.index,.ordinal=browser.job_row,.valid=true};
            copy(r->label,title.index==UINT32_MAX?"Unavailable track":title.title);
            if(browser.view==TRACKS&&!browser.kind){
                *row_slot(browser.job_row)=*r;labels_changed();
            }
            /* This query always belongs to All Tracks, even if entered while
             * it was in flight. Library replacement cancels the owner above. */
            return;
        }
        /* Navigation never reuses a pending query buffer or consumes its result
         * as the newer request. Drain first, then admit the new generation. */
        if(browser.job_epoch!=browser.epoch)return;
        if(completed==QUEUE_MEMBER){
            if(browser.queue_status!=LN_BROWSER_QUEUE_LOADING)return;
            if(track>=ln_music_library_count()){browser.queue_status=LN_BROWSER_QUEUE_INVALID;changed();return;}
            browser.queue.tracks[browser.queue_next++]=track;
            if(browser.queue_next==browser.queue.count)queue_publish();
        }else if(completed==RANGE){
            uint32_t target=browser.kind+(browser.range_phase==2u?1u:0u);
            if(g.kind<target)browser.lo=browser.mid+1u;else browser.hi=browser.mid;
        }else if(browser.job_row>=browser.first&&
                 browser.job_row-browser.first<LN_MUSIC_BROWSER_ROWS){
            struct row *r=row_slot(browser.job_row);
            r->ordinal=browser.job_row;
            if(completed==TITLE){
                r->index=title.index;r->valid=true;
                copy(r->label,title.index==UINT32_MAX?"Unavailable track":title.title);
                if(!browser.kind&&browser.job_row<FIRST_PAGE_ROWS)browser.first_page[browser.job_row]=*r;
                if(browser.job_row-browser.first<browser.visible_rows)labels_changed();
            }else if(completed==GROUP){
                r->index=browser.lower+browser.job_row;r->count=g.count;
                copy(r->label,g.kind==browser.kind?name:"Invalid group");
                if(g.kind!=browser.kind)r->count=0;
                r->valid=true;
                if(browser.job_row-browser.first<browser.visible_rows)labels_changed();
            }
        }
    }
    if(browser.suspended)return;
    if(!browser.visible&&!browser.selecting&&browser.queue_status!=LN_BROWSER_QUEUE_LOADING)return;
    if(browser.queue_status==LN_BROWSER_QUEUE_LOADING){
        if(ln_music_library_group_member(browser.group,browser.queue_next)){
            browser.job=QUEUE_MEMBER;browser.job_epoch=browser.epoch;}
        return;
    }
    if(browser.view==CATEGORIES){
        for(uint32_t i=0;i<preload_count();i++)if(!browser.first_page[i].valid){
            if(ln_music_library_view_row(1u,0,i)){
                browser.job=PRELOAD;browser.job_row=i;browser.job_epoch=browser.epoch;
            }
            break;
        }
        return;
    }
    if(browser.view==GROUPS&&browser.range_phase){
        if(browser.lo==browser.hi){
            if(browser.range_phase==1u){browser.lower=browser.lo;browser.range_phase=2;
                browser.hi=ln_music_library_group_count();}
            else {browser.count=browser.lo-browser.lower;browser.range_phase=0;
                browser.group_lower[browser.kind]=browser.lower;
                browser.group_count[browser.kind]=browser.count;
                browser.group_range_ready[browser.kind]=true;changed();}
            return;
        }
        browser.mid=browser.lo+(browser.hi-browser.lo)/2u;
        if(ln_music_library_group_record(browser.mid)){browser.job=RANGE;browser.job_epoch=browser.epoch;}
        return;
    }
    accept_selection();
    if(browser.queue_status==LN_BROWSER_QUEUE_LOADING||(!browser.visible&&!browser.selecting))return;
    for(uint32_t n=0;n<lookahead();n++){
        /* Resolve a selected row first, then fill the visible cache in order. */
        uint32_t slot=n;
        if(browser.selecting){
            uint32_t chosen=browser.selection-browser.first;
            if(chosen<LN_MUSIC_BROWSER_ROWS){
                if(!n)slot=chosen;else if(n<=chosen)slot=n-1u;
            }
        }
        if(browser.first>=browser.count||slot>=browser.count-browser.first)continue;
        uint32_t ordinal=browser.first+slot;
        if(row_ready(ordinal))continue;
        if(browser.view==GROUPS){
            if(ln_music_library_group(browser.lower+ordinal))browser.job=GROUP;
        }else if(ln_music_library_view_row(browser.kind?2u:1u,browser.group,ordinal))browser.job=TITLE;
        if(browser.job!=NONE){browser.job_epoch=browser.epoch;browser.job_row=ordinal;return;}
        return;
    }
    /* One screen of lookahead is complete. Avoid rescanning cached tags on
     * every music-service wake until navigation invalidates the window. */
    browser.window_ready=true;
}
