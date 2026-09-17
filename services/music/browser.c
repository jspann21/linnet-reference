#include "browser.h"
#include "library.h"
#include "collections.h"
#include "hal/api/platform.h"

enum view { CATEGORIES,GROUPS,TRACKS,PLAYLISTS,LOCAL_TRACKS,ACTIONS,DESTINATION,NAME,CONFIRM };
enum job { NONE,RANGE,GROUP,TITLE,MEMBER,RECORD,RESOLVE,EXPAND };
struct location {enum view view;uint32_t kind,group,count,lower,selected,slot;char title[256];};
struct row {uint32_t ordinal,index,count;bool valid;char label[256];};
static struct {
    struct location here,parents[8];uint32_t depth,first,visible,revision,navigation,epoch,job_epoch,job_row,lo,hi,mid,range;
    struct row rows[LN_MUSIC_BROWSER_ROWS*2];enum job job;
    bool suspended,visible_now,was_ready,search,selection_ready,external,search_return;
    uint32_t restored_selection;
    struct ln_music_browser_queue queue;int status;uint32_t next;
    uint32_t action_row,action_index,action_count,action_group,action_kind;
    bool action_track,action_local;
    const char *notice;
    struct ln_collection draft;uint32_t mapped[LINNET_QUEUE_CAPACITY],positions[LINNET_QUEUE_CAPACITY],scan,resolve_count;
    bool resolving,exporting,choosing,renaming,saved_message,empty_actions;uint32_t export_at,destination;
    struct ln_queue export_queue,expanded;bool expanding,expanded_ready;uint32_t expand_at;
    char name[32];uint32_t name_length;
} b;
static const char *const categories[]={"All Tracks","Artists","Albums","Genres","Composers","Years","Folders","Playlists","Search"};
static const char alphabet[]=" ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'";
static void copy(char *out,const char *in){uint32_t i=0;while(i<255&&in[i]){out[i]=in[i];i++;}out[i]=0;}
static void changed(void){b.revision++;}
static void invalidate(void){++b.epoch;for(uint32_t i=0;i<LN_MUSIC_BROWSER_ROWS*2;i++)b.rows[i].valid=false;changed();}
static struct row *row(uint32_t n){struct row *r=&b.rows[n%(LN_MUSIC_BROWSER_ROWS*2)];return r->valid&&r->ordinal==n?r:0;}
static void navigate(void){b.navigation++;b.first=0;invalidate();b.selection_ready=true;b.restored_selection=b.here.selected;}
static bool push(void){if(b.depth==8)return false;b.parents[b.depth++]=b.here;return true;}
static void enter(enum view view,const char *title){b.here=(struct location){.view=view};copy(b.here.title,title);navigate();}
static uint32_t slots(void){uint32_t n=0;for(uint32_t i=0;i<LN_COLLECTION_SLOTS;i++){const struct ln_collection *p=ln_collection_get(i);if(p&&p->name[0])n++;}return n;}
static uint32_t slot_at(uint32_t n){for(uint32_t i=0;i<LN_COLLECTION_SLOTS;i++){const struct ln_collection *p=ln_collection_get(i);if(p&&p->name[0]){if(!n)return i;n--;}}return UINT32_MAX;}
void ln_music_browser_init(void){b.visible=6;b.visible_now=true;enter(CATEGORIES,"Music");}
void ln_music_browser_suspend(bool value){b.suspended=value;}
void ln_music_browser_set_visible(bool value){b.visible_now=value;}
bool ln_music_browser_window_needed(void){return false;}
bool ln_music_browser_query_idle(void){return b.job==NONE;}
bool ln_music_browser_take_search(void){bool result=b.search;b.search=false;return result;}
void ln_music_browser_publish(void){}
uint32_t ln_music_browser_revision(void){return b.revision+ln_collections_revision();}
uint32_t ln_music_browser_navigation(void){return b.navigation;}
bool ln_music_browser_take_selection(uint32_t *out){if(!out||!b.selection_ready)return false;*out=b.restored_selection;b.selection_ready=false;return true;}
void ln_music_browser_notice(const char *text){b.notice=text;changed();}
uint32_t ln_music_browser_count(void){
    if(b.resolving||b.exporting||b.expanding)return 1;
    switch(b.here.view){case CATEGORIES:return 9;case PLAYLISTS:return slots()+2;case DESTINATION:return slots()+1;
    case NAME:return sizeof alphabet+1;case CONFIRM:return 2;
    case ACTIONS:return b.empty_actions?2:b.action_local?9:4;
    default:return b.here.count?b.here.count:1;}
}
const char *ln_music_browser_title(void){return b.notice?b.notice:b.saved_message?ln_collections_status():b.expanding?"Preparing queue...":b.exporting?"Preparing playlist...":b.resolving?"Finding playlist tracks...":b.here.view==NAME?(b.name_length?b.name:"Enter playlist name"):b.here.title;}
const char *ln_music_browser_label(uint32_t n){
    if(b.resolving||b.exporting||b.expanding)return "Please wait";
    switch(b.here.view){
    case CATEGORIES:return n<9?categories[n]:"";
    case PLAYLISTS:case DESTINATION:{uint32_t count=slots();if(n<count){const struct ln_collection *p=ln_collection_get(slot_at(n));return p?p->name:"";}
        if(!ln_collections_ready())return "Loading playlists...";return n==count?"New playlist...":"Synced playlists";}
    case NAME:{static char letter[2];if(!n)return "Save name";if(n==1)return "Erase last character";if(n-2>=sizeof alphabet-1)return "";letter[0]=alphabet[n-2];letter[1]=0;return letter[0]==' '?"[space]":letter;}
    case CONFIRM:return n?"Delete playlist":"Cancel";
    case ACTIONS:{static const char *const actions[]={"Play","Play Next","Add to Queue","Add to Playlist...","Move up","Move down","Remove track","Rename playlist...","Delete playlist..."};return b.empty_actions?(n?"Delete playlist...":"Rename playlist..."):n<(b.action_local?9u:4u)?actions[n]:"";}
    default:if(!b.here.count)return b.range?"Loading...":"No tracks";struct row *r=row(n);return r?r->label:"Loading...";
    }
}
void ln_music_browser_visible_rows(uint32_t n){b.visible=n?n:1;if(b.visible>LN_MUSIC_BROWSER_ROWS)b.visible=LN_MUSIC_BROWSER_ROWS;}
void ln_music_browser_window(uint32_t n){b.first=n;}
static void groups(uint32_t kind){enter(GROUPS,categories[kind]);b.here.kind=kind;b.range=1;b.lo=0;b.hi=ln_music_library_group_count();}
static void name_begin(bool rename){
    b.renaming=rename;b.name_length=0;
    const char *name=rename?b.draft.name:"";while(name[b.name_length]&&b.name_length<31){b.name[b.name_length]=name[b.name_length];b.name_length++;}b.name[b.name_length]=0;
    enter(NAME,"Playlist name");
}
static bool store_draft(uint32_t slot){
    if(!ln_collection_put(slot,&b.draft)){ln_music_browser_notice(ln_collections_status());return false;}
    b.choosing=false;b.external=false;b.exporting=false;b.depth=0;enter(PLAYLISTS,"Playlists");b.saved_message=true;return true;
}
static void resolve_begin(uint32_t slot){
    const struct ln_collection *p=ln_collection_get(slot);if(!p)return;b.draft=*p;
    enter(LOCAL_TRACKS,b.draft.name);b.here.slot=slot;b.here.count=b.draft.count;b.scan=b.resolve_count=0;b.resolving=b.draft.count!=0;
    for(uint32_t i=0;i<b.draft.count;i++)b.mapped[i]=UINT32_MAX;
}
static void queue_begin(uint32_t count,uint32_t cursor,uint32_t source,uint32_t group,uint32_t action){
    b.queue=(struct ln_music_browser_queue){.count=count,.cursor=cursor,.source=source,.source_group=group,.action=action};
    if(!count||!ln_music_library_identity(b.queue.library_hash)){ln_music_browser_notice("No tracks to add");return;}
    if(action&&count>LINNET_QUEUE_CAPACITY){ln_music_browser_notice("Edit limit: 1024 tracks");return;}
    if(count>LINNET_QUEUE_CAPACITY||(!action&&source&&count>64&&!ln_collections_writable())){b.status=LN_BROWSER_QUEUE_READY;return;}
    b.next=0;b.status=LN_BROWSER_QUEUE_LOADING;b.notice="Preparing...";
    if(source==LN_QUEUE_ALL){for(uint32_t i=0;i<count;i++)b.queue.tracks[i]=i;b.queue.source=0;b.status=LN_BROWSER_QUEUE_READY;}
    changed();
}
bool ln_music_browser_actions(uint32_t selected){
    if(b.resolving||b.exporting||b.expanding||b.status==LN_BROWSER_QUEUE_LOADING)return false;
    if(b.here.view!=TRACKS&&b.here.view!=GROUPS&&b.here.view!=LOCAL_TRACKS&&b.here.view!=PLAYLISTS)return false;
    b.saved_message=false;b.empty_actions=false;b.here.selected=selected;b.action_row=selected;b.action_local=b.here.view==LOCAL_TRACKS;
    if(b.here.view==PLAYLISTS){uint32_t slot=slot_at(selected);if(slot==UINT32_MAX)return false;if(!push())return false;resolve_begin(slot);return true;}
    struct row *r=row(selected);
    if(!b.here.count&&b.action_local){b.empty_actions=true;if(!push())return false;enter(ACTIONS,"Playlist actions");return true;}
    if(!r){ln_music_browser_notice("Wait for track to load");return false;}
    b.action_track=b.here.view!=GROUPS;b.action_index=r->index;b.action_count=r->count;b.action_group=r->index;b.action_kind=b.here.kind;
    if(!push())return false;enter(ACTIONS,r->label);return true;
}
bool ln_music_browser_select(uint32_t n){
    if(b.resolving||b.exporting||b.expanding||b.status==LN_BROWSER_QUEUE_LOADING)return false;
    b.notice=0;b.saved_message=false;b.here.selected=n;
    if(b.here.view==CATEGORIES){if(n==8){b.search=true;return true;}if(!push())return false;
        if(n==7)enter(PLAYLISTS,"Playlists");else if(n)groups(n);else{enter(TRACKS,"All Tracks");b.here.count=ln_music_library_count();}return true;}
    if(b.here.view==PLAYLISTS||b.here.view==DESTINATION){
        uint32_t count=slots(),slot=slot_at(n);bool destination=b.here.view==DESTINATION;
        if(n==count){if(!ln_collections_writable()){ln_music_browser_notice(ln_collections_status());return false;}int free=ln_collection_free();if(free<0){ln_music_browser_notice("All 16 playlists are in use");return false;}b.destination=(uint32_t)free;if(!destination)b.draft=(struct ln_collection){0};push();name_begin(false);return true;}
        if(slot!=UINT32_MAX){if(destination){const struct ln_collection *p=ln_collection_get(slot);if(!p||p->count+b.draft.count>LINNET_QUEUE_CAPACITY){ln_music_browser_notice("Playlist limit: 1024 tracks");return false;}
                for(uint32_t i=b.draft.count;i;i--)b.draft.ids[p->count+i-1]=b.draft.ids[i-1];for(uint32_t i=0;i<p->count;i++)b.draft.ids[i]=p->ids[i];b.draft.count+=p->count;for(uint32_t i=0;i<32;i++)b.draft.name[i]=p->name[i];return store_draft(slot);}
            if(!push())return false;resolve_begin(slot);return true;}
        if(!destination&&n==count+1){if(!push())return false;groups(7);return true;}return false;
    }
    if(b.here.view==NAME){if(!n){if(!b.name_length){ln_music_browser_notice("Enter a playlist name");return false;}
            for(uint32_t i=0;i<LN_COLLECTION_SLOTS;i++){const struct ln_collection *p=ln_collection_get(i);if(i==b.destination||!p)continue;uint32_t j=0;while(b.name[j]&&b.name[j]==p->name[j])j++;if(!b.name[j]&&!p->name[j]){ln_music_browser_notice("Name already in use");return false;}}
            for(uint32_t i=0;i<32;i++)b.draft.name[i]=i<=b.name_length?b.name[i]:0;return store_draft(b.destination);}
        if(n==1){if(b.name_length)b.name[--b.name_length]=0;}else if(n-2<sizeof alphabet-1&&b.name_length<31){b.name[b.name_length++]=alphabet[n-2];b.name[b.name_length]=0;}changed();return true;}
    if(b.here.view==CONFIRM){if(!n)return ln_music_browser_back();b.draft=(struct ln_collection){0};return store_draft(b.destination);}
    if(b.here.view==ACTIONS){
        if(b.empty_actions)n+=7;
        if(n>=4&&b.action_local){struct location *parent=&b.parents[b.depth-1];uint32_t slot=parent->slot,index=b.positions[b.action_row];const struct ln_collection *p=ln_collection_get(slot);if(!p)return false;b.draft=*p;b.destination=slot;
            if(n==7){push();name_begin(true);return true;}if(n==8){push();enter(CONFIRM,"Delete this playlist?");return true;}
            if(index>=b.draft.count)return false;
            if(n==6){for(uint32_t i=index+1;i<b.draft.count;i++)b.draft.ids[i-1]=b.draft.ids[i];b.draft.count--;}
            else {uint32_t to=n==4?(index?index-1:index):(index+1<b.draft.count?index+1:index);uint64_t id=b.draft.ids[to];b.draft.ids[to]=b.draft.ids[index];b.draft.ids[index]=id;parent->selected=to;}
            if(!ln_collection_put(slot,&b.draft)){ln_music_browser_notice(ln_collections_status());return false;}ln_music_browser_back();resolve_begin(slot);return true;}
        if(n>3)return false;
        if(b.action_track){queue_begin(1,0,0,0,n);b.queue.tracks[0]=b.action_index;b.status=LN_BROWSER_QUEUE_READY;}
        else queue_begin(b.action_count,0,LN_QUEUE_GROUP,b.action_group,n);
        return true;
    }
    if(n>=b.here.count)return false;struct row *r=row(n);if(!r)return false;
    if(b.here.view==GROUPS){uint32_t group=r->index,count=r->count;char name[256];copy(name,r->label);if(!push())return false;enter(TRACKS,name);b.here.kind=b.parents[b.depth-1].kind;b.here.group=group;b.here.count=count;return true;}
    if(b.here.view==LOCAL_TRACKS){queue_begin(b.here.count,n,0,0,0);for(uint32_t i=0;i<b.here.count;i++)b.queue.tracks[i]=b.mapped[i];b.status=LN_BROWSER_QUEUE_READY;return true;}
    queue_begin(b.here.count,n,b.here.kind?LN_QUEUE_GROUP:LN_QUEUE_ALL,b.here.group,0);return true;
}
bool ln_music_browser_select_single(uint32_t n){struct row *r=row(n);if(!r)return false;queue_begin(1,0,0,0,0);b.queue.tracks[0]=r->index;b.status=LN_BROWSER_QUEUE_READY;return true;}
bool ln_music_browser_open_album(uint32_t group,uint32_t count,const char *title){if(!count)return false;push();enter(TRACKS,title);b.here.kind=2;b.here.group=group;b.here.count=count;return true;}
bool ln_music_browser_back(void){
    if(b.expanding)return true;
    b.notice=0;b.saved_message=false;b.exporting=b.resolving=false;b.status=LN_BROWSER_QUEUE_IDLE;b.range=0;invalidate();
    if(b.external&&b.here.view==ACTIONS){b.external=false;b.search_return=true;}
    if(!b.depth)return false;b.here=b.parents[--b.depth];navigate();
    if(b.here.view==LOCAL_TRACKS){uint32_t selected=b.here.selected,slot=b.here.slot;resolve_begin(slot);b.here.selected=selected;b.restored_selection=selected;}
    return true;
}
int ln_music_browser_queue_status(void){return b.status;}
bool ln_music_browser_take_queue(struct ln_music_browser_queue *out){if(b.status!=LN_BROWSER_QUEUE_READY||!out)return false;*out=b.queue;b.status=LN_BROWSER_QUEUE_IDLE;b.notice=0;return true;}
bool ln_music_browser_save_queue(const struct ln_queue *q){
    if(!q||!q->count||q->count>LINNET_QUEUE_CAPACITY){ln_music_browser_notice("Save limit: 1024 tracks");return false;}
    if(!ln_collections_writable()){ln_music_browser_notice(ln_collections_status());return false;}
    b.action_kind=0;b.export_queue=*q;b.exporting=true;b.export_at=0;b.draft=(struct ln_collection){0};b.choosing=true;b.notice=0;
    push();enter(DESTINATION,"Add to playlist");return true;
}
bool ln_music_browser_busy(void){return b.job!=NONE||b.range||b.resolving||b.exporting||b.expanding||b.status==LN_BROWSER_QUEUE_LOADING;}
void ln_music_browser_step(void){
    if(ln_music_library_status()!=LN_LIBRARY_READY){b.job=NONE;b.was_ready=false;b.expanding=b.exporting=b.resolving=false;b.status=LN_BROWSER_QUEUE_IDLE;return;}
    if(!b.was_ready){b.was_ready=true;invalidate();}
    if(b.job!=NONE){
        enum job job=b.job;struct ln_music_group g;char name[256];struct ln_music_library_search_row title;struct ln_music_track track;uint32_t member=UINT32_MAX;
        bool done=job==TITLE?ln_music_library_take_view_row(&title):(job==MEMBER||job==EXPAND)?ln_music_library_take_member(&member):job==RECORD||job==RESOLVE?ln_music_library_take_track_record(&track):ln_music_library_take_group(&g,name);
        if(!done)return;b.job=NONE;if(b.job_epoch!=b.epoch)return;
        if(job==RANGE){uint32_t target=b.here.kind+(b.range==2);if(g.kind<target)b.lo=b.mid+1;else b.hi=b.mid;}
        else if(job==EXPAND){if(member>=ln_music_library_count()){b.expanding=false;ln_music_browser_notice("Track unavailable");return;}b.expanded.tracks[b.expand_at]=member;b.expanded.order[b.expand_at]=b.expand_at;b.expand_at++;if(b.expand_at==b.expanded.count){b.expanding=false;b.expanded.source=0;b.expanded_ready=true;changed();}}
        else if(job==MEMBER){if(member>=ln_music_library_count()){b.status=LN_BROWSER_QUEUE_INVALID;b.exporting=false;ln_music_browser_notice("Track unavailable");return;}
            if(b.exporting){b.action_index=member;b.action_kind=1;}else{b.queue.tracks[b.next++]=member;if(b.next==b.queue.count){b.queue.source=0;b.status=LN_BROWSER_QUEUE_READY;}}}
        else if(job==RECORD){b.draft.ids[b.draft.count++]=track.id;b.export_at++;b.action_kind=0;if(b.export_at==b.export_queue.count){b.exporting=false;changed();}}
        else if(job==RESOLVE){for(uint32_t i=0;i<b.draft.count;i++)if(b.draft.ids[i]==track.id)b.mapped[i]=b.scan;b.scan++;
            if(b.scan==ln_music_library_count()){uint32_t count=0;for(uint32_t i=0;i<b.draft.count;i++)if(b.mapped[i]!=UINT32_MAX){b.positions[count]=i;b.mapped[count++]=b.mapped[i];}b.here.count=count;b.resolving=false;if(count!=b.draft.count)ln_music_browser_notice("Missing tracks omitted");changed();}}
        else {struct row *r=&b.rows[b.job_row%(LN_MUSIC_BROWSER_ROWS*2)];*r=(struct row){.ordinal=b.job_row,.valid=true};
            if(job==TITLE){r->index=title.index;copy(r->label,title.title);}else{r->index=b.here.lower+b.job_row;r->count=g.count;copy(r->label,name);}changed();}
    }
    if(b.suspended)return;
    if(!b.visible_now&&!b.exporting&&!b.expanding&&b.status!=LN_BROWSER_QUEUE_LOADING)return;
    if(b.expanding){uint32_t ordinal;if(ln_queue_track_at(&b.export_queue,b.expand_at,&ordinal)&&ln_music_library_group_member(b.export_queue.source_group,ordinal))b.job=EXPAND;
    }else if(b.exporting){uint32_t ordinal;if(!ln_queue_track_at(&b.export_queue,b.export_at,&ordinal)){b.exporting=false;ln_music_browser_notice("Queue changed");return;}
        if(b.export_queue.source==LN_QUEUE_GROUP&&!b.action_kind){if(ln_music_library_group_member(b.export_queue.source_group,ordinal))b.job=MEMBER;}
        else if(ln_music_library_track_record(b.export_queue.source==LN_QUEUE_GROUP?b.action_index:ordinal))b.job=RECORD;
    }else if(b.resolving){if(!ln_music_library_count()){b.resolving=false;b.here.count=0;}else if(ln_music_library_track_record(b.scan))b.job=RESOLVE;
    }else if(b.status==LN_BROWSER_QUEUE_LOADING){if(ln_music_library_group_member(b.queue.source_group,b.next))b.job=MEMBER;
    }else if(b.range){if(b.lo==b.hi){if(b.range==1){b.here.lower=b.lo;b.range=2;b.hi=ln_music_library_group_count();}else{b.here.count=b.lo-b.here.lower;b.range=0;changed();}return;}
        b.mid=b.lo+(b.hi-b.lo)/2;if(ln_music_library_group_record(b.mid))b.job=RANGE;
    }else if(b.here.view==GROUPS||b.here.view==TRACKS||b.here.view==LOCAL_TRACKS){
        for(uint32_t i=b.first;i<b.here.count&&i<b.first+b.visible*2;i++){if(row(i))continue;b.job_row=i;
            if(b.here.view==GROUPS){if(ln_music_library_group(b.here.lower+i))b.job=GROUP;}
            else if(ln_music_library_view_row(b.here.view==LOCAL_TRACKS?0:b.here.kind?2:1,b.here.group,b.here.view==LOCAL_TRACKS?b.mapped[i]:i))b.job=TITLE;break;}
    }
    if(b.job!=NONE)b.job_epoch=b.epoch;
}

bool ln_music_browser_expand(const struct ln_queue *q){
    if(!q||q->count>LINNET_QUEUE_CAPACITY||b.expanding||b.exporting)return false;
    b.export_queue=*q;b.expanded=*q;b.expand_at=0;b.expanded_ready=false;
    if(q->source==LN_QUEUE_GROUP){b.expanding=true;return true;}
    for(uint32_t i=0;i<q->count;i++){uint32_t index;if(!ln_queue_track_at(q,i,&index))return false;b.expanded.tracks[i]=index;b.expanded.order[i]=i;}
    b.expanded.source=0;b.expanded_ready=true;return true;
}
bool ln_music_browser_take_expanded(struct ln_queue *out){if(!out||!b.expanded_ready)return false;*out=b.expanded;b.expanded_ready=false;return true;}

bool ln_music_browser_external_actions(uint32_t index,uint32_t kind,uint32_t count,const char *title){
    if(b.exporting||b.expanding||!push())return false;
    b.action_track=!kind;b.action_local=b.empty_actions=false;b.action_index=index;b.action_group=index&~LN_MUSIC_SEARCH_GROUP;b.action_count=count;b.action_kind=kind;b.external=true;
    enter(ACTIONS,title);return true;
}
bool ln_music_browser_take_search_return(void){bool value=b.search_return;b.search_return=false;return value;}

const char *ln_music_browser_hint(void){
    if(b.here.view==TRACKS||b.here.view==LOCAL_TRACKS||b.here.view==GROUPS)return "Right: Actions  Menu: Back";
    return "Select: Choose  Menu: Back";
}
