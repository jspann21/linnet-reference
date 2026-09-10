#include "search.h"
#include "library.h"
#include "browser.h"
static const char alphabet[]="abcdefghijklmnopqrstuvwxyz0123456789 -'.";
static struct ln_music_library_search_row rows[LN_MUSIC_SEARCH_ROWS];
static char prefix[LN_MUSIC_SEARCH_PREFIX+1],character[2],group_title[256],label[272];
static uint32_t length,first,filled,revision,navigation,epoch,admitted_epoch,selected_track;
static uint32_t group_index,search_first;
static bool opened,closing,results,pending,complete,more,track_ready,in_group,pending_group;
static void reset_page(uint32_t start){first=start;filled=0;complete=more=false;++epoch;++revision;}
void ln_music_search_open(void){
    opened=true;closing=false;results=false;track_ready=false;in_group=false;
    ln_music_browser_suspend(true);reset_page(0);++navigation;
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
        pending=false;complete=true;more=false;
        if(closing){ln_music_browser_suspend(false);closing=false;}
        return;
    }
    if(pending){
        struct ln_music_library_search_row row;
        if(pending_group?!ln_music_library_take_view_row(&row):!ln_music_library_take_search_row(&row))return;
        pending=false;
        if(admitted_epoch==epoch&&opened&&results){
            if(row.index==UINT32_MAX)complete=true;
            else if(filled<LN_MUSIC_SEARCH_ROWS)rows[filled++]=row;
            else {more=true;complete=true;}
            ++revision;
        }
    }
    if(closing){ln_music_browser_suspend(false);closing=false;return;}
    if(!results||!length||complete||!ln_music_browser_query_idle())return;
    if(in_group?ln_music_library_view_row(2,group_index,first+filled):ln_music_library_search_at(prefix,first+filled)){
        pending=true;pending_group=in_group;admitted_epoch=epoch;
    }
}
bool ln_music_search_busy(void){return closing||pending||(opened&&results&&length&&!complete);}
bool ln_music_search_active(void){return opened||closing;}
uint32_t ln_music_search_count(void){
    if(!results)return sizeof alphabet;
    return (first?1u:0u)+filled+(!complete||more?1u:0u)+(complete&&!filled?1u:0u);
}
const char *ln_music_search_label(uint32_t row){
    if(!results){
        if(row==sizeof alphabet-1u)return "Show results >";
        if(row>=sizeof alphabet-1u)return "";
        if(alphabet[row]==' ')return "[space]";
        character[0]=alphabet[row];return character;
    }
    if(first){if(!row)return "< Previous results";--row;}
    if(row<filled){
        if(!rows[row].kind)return rows[row].title;
        const char *tag=rows[row].kind==1?"Artist: ":"Album: ";
        uint32_t n=0,i=0;
        while(tag[i])label[n++]=tag[i++];
        i=0;while(rows[row].title[i])label[n++]=rows[row].title[i++];label[n]=0;
        return label;
    }
    if(row!=filled)return "";
    if(!complete)return "Searching...";
    if(more)return "More results >";
    return ln_music_library_status()!=LN_LIBRARY_READY?"Library unavailable":"No matches";
}
const char *ln_music_search_prefix(void){return length?prefix:"Enter name prefix";}
const char *ln_music_search_hint(void){return results?(in_group?"Select: play  Menu: results":"Select: open/play  Menu: edit"):"Select:add Left:erase Right:find";}
const char *ln_music_search_title(void){return in_group?group_title:results?"Search results":"Search music";}
uint32_t ln_music_search_revision(void){return revision;}
uint32_t ln_music_search_navigation(void){return navigation;}
void ln_music_search_right(void){if(opened&&length&&!results){results=true;reset_page(0);++navigation;}}
void ln_music_search_left(void){
    if(!opened)return;
    if(results){(void)ln_music_search_back();return;}
    if(length){prefix[--length]=0;reset_page(0);}
}
bool ln_music_search_select(uint32_t row){
    if(!opened)return false;
    if(!results){
        if(row==sizeof alphabet-1u){ln_music_search_right();return length!=0;}
        if(row>=sizeof alphabet-1u||length==LN_MUSIC_SEARCH_PREFIX)return false;
        prefix[length++]=alphabet[row];prefix[length]=0;reset_page(0);return true;
    }
    if(first){if(!row){reset_page(first-LN_MUSIC_SEARCH_ROWS);++navigation;return true;}--row;}
    if(row<filled){
        if(rows[row].kind){
            search_first=first;group_index=rows[row].index&~LN_MUSIC_SEARCH_GROUP;in_group=true;
            uint32_t i=0;do{group_title[i]=rows[row].title[i];}while(rows[row].title[i++]&&i<256u);
            reset_page(0);++navigation;return true;
        }
        selected_track=rows[row].index;track_ready=true;return true;
    }
    if(row==filled&&complete&&more){reset_page(first+LN_MUSIC_SEARCH_ROWS);++navigation;return true;}
    return false;
}
bool ln_music_search_back(void){
    if(in_group){in_group=false;reset_page(search_first);++navigation;return true;}
    if(results){results=false;reset_page(0);++navigation;return true;}
    ln_music_search_close();return false;
}
void ln_music_search_window(uint32_t first_visible){(void)first_visible;}
bool ln_music_search_take_track(uint32_t *track){
    if(!track||!track_ready)return false;
    *track=selected_track;track_ready=false;return true;
}
