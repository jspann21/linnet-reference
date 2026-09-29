#include "search.h"
#include "library.h"
#include "browser.h"
#if !defined(LINNET_PROFILE_RELEASE)
#include "hal/api/platform.h"
static uint32_t query_started_us,first_ready_us,window_ready_us;
#endif
static const char alphabet[]="abcdefghijklmnopqrstuvwxyz0123456789 -'.";
struct cached_row { struct ln_music_library_search_row value; uint32_t ordinal; bool valid; };
static struct cached_row rows[LN_MUSIC_SEARCH_ROWS*2u];
static char prefix[LN_MUSIC_SEARCH_PREFIX+1],character[2],group_title[256],label[272];
static uint32_t length,first,known,total,revision,navigation,epoch,admitted_epoch,pending_ordinal,selected_track;
static uint32_t group_index,group_count,search_first,search_row,selected_ordinal,restore_row;
static bool restore_selection;
static bool opened,closing,results,pending,complete,track_ready,in_group,pending_group,window_ready,library_waiting;
static struct cached_row *row_slot(uint32_t ordinal){return &rows[ordinal%(LN_MUSIC_SEARCH_ROWS*2u)];}
static bool row_ready(uint32_t ordinal){struct cached_row *r=row_slot(ordinal);return r->valid&&r->ordinal==ordinal;}
static void reset_results(uint32_t start){
    first=start;known=total=0;complete=window_ready=false;restore_selection=false;
#if !defined(LINNET_PROFILE_RELEASE)
    query_started_us=results&&length?ln_time_us():0;
    first_ready_us=window_ready_us=0;
#endif
    for(uint32_t i=0;i<LN_MUSIC_SEARCH_ROWS*2u;++i)rows[i].valid=false;
    ++epoch;++revision;
}
void ln_music_search_open(void){
    opened=true;closing=false;results=false;track_ready=false;in_group=false;
    ln_music_browser_suspend(true);reset_results(0);++navigation;
}
void ln_music_search_close(void){opened=false;closing=true;track_ready=false;++epoch;++revision;}
void ln_music_search_resume(void){
    if(opened)return;
    opened=true;closing=false;track_ready=false;++epoch;++revision;
    ln_music_browser_suspend(true);
}
void ln_music_search_step(void){
    if(!opened&&!closing)return;
    if(ln_music_library_status()!=LN_LIBRARY_READY){
        pending=false;complete=window_ready=library_waiting=true;total=known;
        if(closing){ln_music_browser_suspend(false);closing=false;}
        return;
    }
    if(library_waiting){library_waiting=false;reset_results(first);}
    if(pending){
        struct ln_music_library_search_row row;
        if(pending_group?!ln_music_library_take_view_row(&row):!ln_music_library_take_search_row(&row))return;
        pending=false;
        if(admitted_epoch==epoch&&opened&&results){
            if(row.index==UINT32_MAX){complete=true;total=pending_ordinal;}
            else {
                struct cached_row *cached=row_slot(pending_ordinal);
                cached->value=row;cached->ordinal=pending_ordinal;cached->valid=true;
                if(pending_ordinal>=known)known=pending_ordinal+1u;
            }
#if !defined(LINNET_PROFILE_RELEASE)
            if(!first_ready_us)first_ready_us=ln_time_us();
#endif
        }
    }
    if(closing){ln_music_browser_suspend(false);closing=false;return;}
    if(!results||!length||!ln_music_browser_query_idle())return;
    uint32_t limit=first+LN_MUSIC_SEARCH_ROWS,ordinal=first;
    if(complete&&limit>total)limit=total;
    while(ordinal<limit&&row_ready(ordinal))++ordinal;
    bool ready=ordinal>=limit;
    /* Publish a complete visible window once; partial row redraws otherwise
     * steal time from the remaining disk reads and audio work. */
    if(ready&&!window_ready)++revision;
    window_ready=ready;
#if !defined(LINNET_PROFILE_RELEASE)
    if(window_ready&&!window_ready_us)window_ready_us=ln_time_us();
#endif
    if(window_ready)return;
    if(in_group?ln_music_library_view_row(2,group_index,ordinal):ln_music_library_search_at(prefix,ordinal)){
        pending_ordinal=ordinal;
        pending=true;pending_group=in_group;admitted_epoch=epoch;
    }
}
bool ln_music_search_busy(void){return closing||pending||(opened&&results&&length&&!window_ready);}
bool ln_music_search_query_pending(void){return pending;}
#if !defined(LINNET_PROFILE_RELEASE)
void ln_music_search_diagnostics(uint32_t out[16]){
    uint32_t words[16]={0x48435253u,0,opened,results,ln_music_search_busy(),first,known,total,
        revision,query_started_us,first_ready_us,window_ready_us,ln_time_us(),in_group,complete,window_ready};
    for(uint32_t i=0;i<16u;i++)out[i]=words[i];
}
#endif
bool ln_music_search_active(void){return opened||closing;}
uint32_t ln_music_search_count(void){
    if(!results)return sizeof alphabet;
    if(complete)return total?total:1u;
    return known+1u;
}
const char *ln_music_search_label(uint32_t row){
    if(!results){
        if(row==sizeof alphabet-1u)return "Show results >";
        if(row>=sizeof alphabet-1u)return "";
        if(alphabet[row]==' ')return "[space]";
        character[0]=alphabet[row];return character;
    }
    if(complete&&!total)return row?"":ln_music_library_status()!=LN_LIBRARY_READY?"Library unavailable":"No matches";
    if(row>=known)return !complete&&row==known?"Searching...":"";
    if(!row_ready(row))return "Loading...";
    const struct ln_music_library_search_row *result=&row_slot(row)->value;
    {
        if(!result->kind)return result->title;
        const char *tag=result->kind==1?"Artist: ":"Album: ";
        uint32_t n=0,i=0;
        while(tag[i])label[n++]=tag[i++];
        i=0;while(result->title[i])label[n++]=result->title[i++];label[n]=0;
        return label;
    }
}
const char *ln_music_search_prefix(void){return length?prefix:"Enter name prefix";}
const char *ln_music_search_hint(void){return results?(in_group?"Right: Actions  Menu: Results":"Right: Actions  Menu: Edit"):"Select: Add  Left: Erase  Right: Find";}
const char *ln_music_search_title(void){return in_group?group_title:results?"Search results":"Search music";}
uint32_t ln_music_search_revision(void){return revision;}
uint32_t ln_music_search_navigation(void){return navigation;}
void ln_music_search_right(void){if(opened&&length&&!results){results=true;reset_results(0);++navigation;}}
void ln_music_search_left(void){
    if(!opened)return;
    if(results){(void)ln_music_search_back();return;}
    if(length){prefix[--length]=0;reset_results(0);}
}
bool ln_music_search_select(uint32_t row){
    if(!opened)return false;
    if(!results){
        if(row==sizeof alphabet-1u){ln_music_search_right();return length!=0;}
        if(row>=sizeof alphabet-1u||length==LN_MUSIC_SEARCH_PREFIX)return false;
        prefix[length++]=alphabet[row];prefix[length]=0;reset_results(0);return true;
    }
    if(row<known&&row_ready(row)){
        const struct ln_music_library_search_row *result=&row_slot(row)->value;
        if(result->kind){
            search_first=first;search_row=row;
            group_index=result->index&~LN_MUSIC_SEARCH_GROUP;group_count=result->count;in_group=true;
            uint32_t i=0;do{group_title[i]=result->title[i];}while(result->title[i++]&&i<256u);
            reset_results(0);++navigation;return true;
        }
        selected_track=result->index;selected_ordinal=row;track_ready=true;return true;
    }
    return false;
}
bool ln_music_search_back(void){
    if(in_group){in_group=false;reset_results(search_first);restore_row=search_row;known=restore_row+1u;restore_selection=true;++navigation;return true;}
    if(results){results=false;reset_results(0);++navigation;return true;}
    ln_music_search_close();return false;
}
void ln_music_search_window(uint32_t first_visible){
    if(!results||first_visible==first)return;
    first=first_visible;window_ready=false;++epoch;++revision;
}
bool ln_music_search_take_selection(uint32_t *row){
    if(!row||!restore_selection)return false;
    *row=restore_row;restore_selection=false;return true;
}
bool ln_music_search_take_queue(struct ln_music_browser_queue *queue){
    if(!queue||!track_ready)return false;
    track_ready=false;*queue=(struct ln_music_browser_queue){0};
    if(!ln_music_library_identity(queue->library_hash))return false;
    if(in_group){
        queue->source=LN_QUEUE_GROUP;queue->source_group=group_index;
        queue->count=group_count;queue->cursor=selected_ordinal;
    }else {queue->count=1;queue->tracks[0]=selected_track;}
    return true;
}

bool ln_music_search_actions(uint32_t index){
    if(!opened||!results||index>=known||!row_ready(index))return false;
    const struct ln_music_library_search_row *r=&row_slot(index)->value;
    if(!ln_music_browser_external_actions(r->index,r->kind,r->count,r->title))return false;
    ln_music_search_close();return true;
}
