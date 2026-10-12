#include "queue_view.h"
#include "library.h"
#include "hal/api/platform.h"
static struct {
    struct ln_queue queue;
    char labels[LN_QUEUE_VIEW_ROWS][259];
    bool valid[LN_QUEUE_VIEW_ROWS],opened,pending,was_ready;
    uint32_t queue_revision,first,epoch,revision,job_epoch,job_row,visible_rows;
} view;
static void invalidate(void){
    ++view.epoch;++view.revision;
    for(uint32_t i=0;i<LN_QUEUE_VIEW_ROWS;i++)view.valid[i]=false;
}
static bool same_labels(const struct ln_queue *a,const struct ln_queue *b){
    if(a->source!=b->source||a->source_group!=b->source_group||a->count!=b->count)return false;
    for(uint32_t i=0;i<32u;i++)if(a->library_identity[i]!=b->library_identity[i])return false;
    if(a->source){
        if(a->stride!=b->stride||a->offset!=b->offset||a->inverse!=b->inverse||
           a->source_count!=b->source_count||a->excluded_count!=b->excluded_count)return false;
        for(uint32_t i=0;i<a->excluded_count;i++)if(a->excluded[i]!=b->excluded[i])return false;
    }else for(uint32_t i=0;i<a->count;i++)
        if(a->tracks[i]!=b->tracks[i]||a->order[i]!=b->order[i])return false;
    return true;
}
void ln_music_queue_view_update(const struct ln_queue *queue,uint32_t queue_revision){
    if(!queue||!view.opened||view.queue_revision==queue_revision)return;
    bool retained=same_labels(&view.queue,queue);
    view.queue=*queue;view.queue_revision=queue_revision;
    if(view.first>=queue->count)view.first=queue->count?queue->count-1u:0;
    if(!retained){invalidate();return;}
    bool changed=false;
    for(uint32_t i=0;i<LN_QUEUE_VIEW_ROWS&&view.first+i<queue->count;i++)if(view.valid[i]){
        char marker=view.first+i==queue->cursor?'>':' ';
        if(view.labels[i][0]!=marker){view.labels[i][0]=marker;changed=true;}
    }
    if(changed)++view.revision;
}
void ln_music_queue_view_open(const struct ln_queue *queue,uint32_t queue_revision){
    if(!queue)return;
    view.opened=true;view.queue=*queue;view.queue_revision=queue_revision;
    if(!view.visible_rows)view.visible_rows=6u;
    view.was_ready=ln_music_library_status()==LN_LIBRARY_READY;
    view.first=queue->count?(queue->cursor/6u)*6u:0;invalidate();
}
void ln_music_queue_view_close(void){view.opened=false;invalidate();}
void ln_music_queue_view_visible_rows(uint32_t rows){
    view.visible_rows=rows?rows:1u;
    if(view.visible_rows>LN_QUEUE_VIEW_ROWS)view.visible_rows=LN_QUEUE_VIEW_ROWS;
}
void ln_music_queue_view_window(uint32_t first){
    if(!view.opened)return;
    if(first>=view.queue.count)first=view.queue.count?view.queue.count-1u:0;
    if(view.first!=first){
        uint32_t old=view.first;
        for(uint32_t n=0;n<LN_QUEUE_VIEW_ROWS;n++){
            uint32_t i=first>old?n:LN_QUEUE_VIEW_ROWS-1u-n,row=first+i;
            if(row>=old&&row-old<LN_QUEUE_VIEW_ROWS){
                uint32_t source=row-old;
                for(uint32_t c=0;c<sizeof(view.labels[i]);c++)view.labels[i][c]=view.labels[source][c];
                view.valid[i]=view.valid[source];
            }else view.valid[i]=false;
        }
        view.first=first;++view.revision;
    }
}
uint32_t ln_music_queue_view_count(void){return view.opened?view.queue.count:0;}
uint32_t ln_music_queue_view_revision(void){return view.revision;}
bool ln_music_queue_view_busy(void){
    if(view.pending)return true;
    if(view.opened)for(uint32_t i=0;i<LN_QUEUE_VIEW_ROWS&&view.first+i<view.queue.count;i++)
        if(!view.valid[i])return true;
    return false;
}
const char *ln_music_queue_view_label(uint32_t row){
    if(!view.opened||row>=view.queue.count)return "";
    if(row<view.first||row-view.first>=LN_QUEUE_VIEW_ROWS||!view.valid[row-view.first])return "Loading...";
    return view.labels[row-view.first];
}
static void publish(uint32_t row,const char *title,bool notify){
    if(row<view.first||row-view.first>=LN_QUEUE_VIEW_ROWS)return;
    uint32_t slot=row-view.first;char *out=view.labels[slot];
    out[0]=row==view.queue.cursor?'>':' ';out[1]=' ';
    uint32_t i=0;while(i<255u&&title[i]){out[i+2]=title[i];i++;}out[i+2]=0;
    view.valid[slot]=true;
    /* Publish one complete viewport; speculative lookahead never repaints. */
    if(!notify||slot>=view.visible_rows)return;
    for(uint32_t n=0;n<view.visible_rows&&view.first+n<view.queue.count;n++)
        if(!view.valid[n])return;
    ++view.revision;
}
bool ln_music_queue_view_prepare(void){
    if(!view.opened||ln_music_library_status()!=LN_LIBRARY_READY)return false;
    uint8_t identity[32];if(!ln_music_library_identity(identity))return false;
    for(uint32_t i=0;i<32u;++i)if(identity[i]!=view.queue.library_identity[i])return false;
    bool filled=false;uint32_t started=ln_time_us();
    for(uint32_t i=0;i<view.visible_rows&&view.first+i<view.queue.count;++i){
        if(view.valid[i])continue;uint32_t track;
        if(!ln_queue_track_at(&view.queue,view.first+i,&track))continue;
        if(view.queue.source==LN_QUEUE_GROUP&&
           !ln_music_library_cached_member(view.queue.source_group&~LN_QUEUE_REVERSE,track,&track))continue;
        const char *title=ln_music_library_title(track);
        if(title){publish(view.first+i,title,false);filled=true;}
        if((uint32_t)(ln_time_us()-started)>=250u)break;
    }
    return filled;
}
void ln_music_queue_view_step(bool allow_query){
    if(ln_music_library_status()!=LN_LIBRARY_READY){
        view.pending=false;view.was_ready=false;
        if(view.opened)for(uint32_t i=0;i<LN_QUEUE_VIEW_ROWS&&view.first+i<view.queue.count;i++)
            if(!view.valid[i])publish(view.first+i,"Library unavailable",true);
        return;
    }
    if(!view.was_ready){view.was_ready=true;if(view.opened)invalidate();}
    if(view.pending){
        struct ln_music_library_search_row row;
        if(!ln_music_library_take_view_row(&row))return;
        view.pending=false;
        if(view.opened&&view.job_epoch==view.epoch)
            publish(view.job_row,row.index==UINT32_MAX?"Unavailable track":row.title,true);
    }
    if(!view.opened||!allow_query)return;
    uint8_t identity[32];bool matched=ln_music_library_identity(identity);
    for(uint32_t i=0;i<32&&matched;i++)if(identity[i]!=view.queue.library_identity[i])matched=false;
    for(uint32_t i=0;i<LN_QUEUE_VIEW_ROWS&&view.first+i<view.queue.count;i++){
        if(view.valid[i])continue;uint32_t ordinal;
        if(!matched){publish(view.first+i,"Library changed",true);return;}
        if(!ln_queue_track_at(&view.queue,view.first+i,&ordinal)){publish(view.first+i,"Invalid queue entry",true);return;}
        if(ln_music_library_view_row(view.queue.source,view.queue.source_group,ordinal)){
            view.pending=true;view.job_epoch=view.epoch;view.job_row=view.first+i;
        }
        return;
    }
}
bool ln_music_queue_view_query_pending(void){return view.pending;}
