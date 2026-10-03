#include "services/music/controller.h"
#include "services/music/player.h"
#include "services/music/artwork.h"
#include "services/music/queue.h"
#include "services/music/history.h"
#include "services/music/browser.h"
#include "services/music/profile.h"
#include "services/music/settings.h"
#include "services/display/settings.h"
#include "services/music/search.h"
#include "services/music/queue_view.h"
#include "services/storage/storage.h"
#if defined(LINNET_PHOTOS)
#include "services/photos/photos.h"
#endif
#include "services/state/store.h"
#include "hal/api/audio.h"
#include "hal/api/platform.h"
static struct ln_queue queue;
static struct ln_music_profile profile;
static struct ln_music_library_row current,waiting;
static bool have_current,have_waiting,active,restored,selecting,persist_failed;
static uint32_t revision,saved_revision,skipped;
static uint32_t restore_attempts,restore_retry_at,restore_revision;
static uint8_t resume[LN_STATE_PAYLOAD_MAX];
static uint64_t requested_position;
static bool headphone_known,headphones;
static struct ln_music_library_row upcoming;
static bool prefetching,next_ready,next_armed,next_failed;
static bool manual_next_pending;
static uint32_t next_index,next_token;
static uint32_t resolver_kind,resolver_token,resolver_ordinal,next_ordinal,current_cursor,waiting_cursor;
static bool show_now_playing;
static bool shutting_down,stepping,pause_captured;
static bool queue_opened;
static uint32_t queue_choice,queue_choice_revision;
static const char *notice;
#define LN_MUSIC_VOLUME_RETRY_US 100000u
static uint32_t volume_retry_at;
static bool volume_retry_pending;
static bool next_queue_cursor(uint32_t *cursor){
    if(!queue.count)return false;
    if(queue.repeat==LINNET_QUEUE_REPEAT_ONE)*cursor=queue.cursor;
    else if(queue.cursor+1u<queue.count)*cursor=queue.cursor+1u;
    else if(queue.repeat==LINNET_QUEUE_REPEAT_ALL)*cursor=0;
    else return false;
    return true;
}
const char *ln_music_notice(void){return notice;}
static void remember_position(void);
static void discard_next(bool restarting){
    ln_music_library_cancel_prefetch();
    prefetching=next_ready=next_armed=next_failed=false;
    manual_next_pending=false;
    if(resolver_kind==2)resolver_kind=0;
    if(!ln_player_cancel_next()){
        if(restarting)ln_player_stop_for_restart();else ln_player_stop();}
}
static bool same(const uint8_t*a,const uint8_t*b){for(uint32_t i=0;i<32;++i)if(a[i]!=b[i])return false;return true;}
static bool select_index(uint32_t index){
    have_waiting=false;resolver_kind=0;notice=0;discard_next(true);waiting_cursor=queue.cursor;
    selecting=ln_music_library_select(index);return selecting;
}
static bool resolve_queue(uint32_t ordinal,uint32_t kind){
    if(queue.source!=LN_QUEUE_GROUP){
        if(kind==1)return select_index(ordinal);
        next_index=ordinal;return prefetching=ln_music_library_prefetch(ordinal);
    }
    uint32_t token=resolver_token+1u;if(!token)token=1;
    if(!ln_music_library_queue_member(queue.source_group,ordinal,token))return false;
    resolver_kind=kind;resolver_ordinal=ordinal;resolver_token=token;return true;
}
static bool select_current(void){
    uint32_t ordinal;if(!ln_queue_current(&queue,&ordinal))return false;
    have_waiting=selecting=false;resolver_kind=0;discard_next(true);
    return resolve_queue(ordinal,1);
}
void ln_music_queue_open(void){
    queue_opened=true;ln_music_search_close();ln_music_browser_suspend(true);
    ln_music_queue_view_open(&queue,revision);
}
void ln_music_queue_close(void){queue_opened=false;ln_music_queue_view_close();}
void ln_music_queue_choose(uint32_t row){queue_choice=row;queue_choice_revision=revision;}
bool ln_music_queue_edit(uint32_t action){
    if(shutting_down||manual_next_pending||selecting||have_waiting||resolver_kind==1||queue_choice_revision!=revision||queue_choice>=queue.count||action>4)return false;
    if(action==4){int32_t volume=queue.volume_db_tenths;uint32_t repeat=queue.repeat;
        ln_music_stop();ln_queue_init(&queue,ln_time_us());(void)ln_music_library_identity(queue.library_identity);queue.volume_db_tenths=volume;queue.repeat=repeat;++revision;return true;}
    remember_position();uint32_t occurrence;
    if(queue.source){if(!ln_queue_track_at(&queue,queue_choice,&occurrence))return false;}
    else occurrence=queue.order[queue_choice];
    bool was_current=queue_choice==queue.cursor,accepted=false;
    if(action&& !ln_player_cancel_next()){notice="Track change in progress";++revision;return false;}
    if(action==0){
        accepted=ln_queue_select_at(&queue,queue_choice);
        if(accepted){active=true;requested_position=0;accepted=select_current();show_now_playing=accepted;}
    }else if(action==1){
        accepted=ln_queue_remove_occurrence(&queue,occurrence);
        if(accepted){
            discard_next(true);resolver_kind=0;
            if(was_current){ln_player_stop_for_restart();requested_position=0;active=queue.count!=0;
                if(active)(void)select_current();else ln_player_stop();}
            else current_cursor=queue.cursor;
        }
    }else {
        if(!queue.source&&queue.shuffled){
            uint32_t target=action==2?(queue_choice?queue_choice-1:queue_choice):(queue_choice+1<queue.count?queue_choice+1:queue_choice);
            uint32_t other=queue.order[target];queue.order[target]=queue.order[queue_choice];queue.order[queue_choice]=other;
            if(queue.cursor==queue_choice)queue.cursor=target;else if(queue.cursor==target)queue.cursor=queue_choice;
            accepted=true;
        }else{
            uint32_t target=action==2?(occurrence?occurrence-1:occurrence):(occurrence+1<queue.count?occurrence+1:occurrence);
            accepted=ln_queue_move_occurrence(&queue,occurrence,target);
        }
        if(accepted){discard_next(true);resolver_kind=0;current_cursor=queue.cursor;}
    }
    if(accepted){notice=0;++revision;}else {notice="Queue edit unavailable";++revision;}
    return accepted;
}
void ln_music_init(void){restore_attempts=restore_retry_at=0;restore_revision=revision;volume_retry_pending=false;volume_retry_at=0;ln_queue_init(&queue,ln_time_us());ln_music_profile_default(&profile);ln_music_library_init();ln_music_browser_init();ln_music_history_init();}
bool ln_music_take_now_playing(void){bool show=show_now_playing;show_now_playing=false;return show;}
const struct ln_music_library_row *ln_music_current(void){return have_current?&current:0;}
bool ln_music_queue_position(uint32_t *position,uint32_t *count){
    if(!position||!count||!have_current||selecting||have_waiting||resolver_kind==1||
       !queue.count||queue.cursor>=queue.count||current_cursor!=queue.cursor)return false;
    *position=queue.cursor+1u;*count=queue.count;return true;
}
uint32_t ln_music_revision(void){return revision+ln_music_history_revision();}
const char *ln_music_sound_label(uint32_t index){
    static char balance[24],preamp[24];
    static const char *const modes[]={"Channels: Stereo","Channels: Mono","Channels: Left","Channels: Right","Channels: Karaoke"};
    if(index==0)return profile.preset==LN_MUSIC_EQ_BASS?"EQ: Bass":profile.preset==LN_MUSIC_EQ_VOICE?"EQ: Voice":"EQ: Flat";
    if(index==1)return profile.replaygain?"ReplayGain: On":"ReplayGain: Off";
    if(index==2)return profile.crossfeed?"Crossfeed: On":"Crossfeed: Off";
    if(index==3){
        if(!profile.balance)return "Balance: Center";
        const char *prefix=profile.balance<0?"Balance: L ":"Balance: R ";uint32_t n=0;
        while(prefix[n]){balance[n]=prefix[n];++n;}uint32_t value=(uint32_t)(profile.balance<0?-profile.balance:profile.balance)/10u;
        if(value>=100)balance[n++]='1';if(value>=10)balance[n++]=(char)('0'+value/10u%10u);
        balance[n++]=(char)('0'+value%10u);balance[n++]='%';balance[n]=0;return balance;
    }
    if(index==4)return modes[profile.mode];
    if(index==5){uint32_t value=(uint32_t)(-profile.preamp_db_q16)/65536u,n=0;const char *prefix="Preamp: -";
        while(prefix[n]){preamp[n]=prefix[n];++n;}if(value>=10)preamp[n++]=(char)('0'+value/10u);
        preamp[n++]=(char)('0'+value%10u);preamp[n++]=' ';preamp[n++]='d';preamp[n++]='B';preamp[n]=0;return preamp;}
    return "";
}
bool ln_music_sound_adjust(uint32_t index,int32_t direction){
    if(shutting_down||manual_next_pending||index>5||!direction)return false;
    struct ln_music_profile next=profile;bool up=direction>0;
    if(index==0)next.preset=(next.preset+(up?1u:2u))%3u;
    else if(index==1)next.replaygain=!next.replaygain;
    else if(index==2)next.crossfeed=!next.crossfeed;
    else if(index==3){next.balance+=up?100:-100;if(next.balance>1000)next.balance=1000;if(next.balance< -1000)next.balance=-1000;}
    else if(index==4)next.mode=(next.mode+(up?1u:4u))%5u;
    else {next.preamp_db_q16+=up?65536:-65536;if(next.preamp_db_q16>0)next.preamp_db_q16=0;if(next.preamp_db_q16< -24*65536)next.preamp_db_q16=-24*65536;}
    if(!ln_music_profile_valid(&next))return false;
    /* Profiles apply at the next track boundary, keeping current PCM coherent.
     * A committed join is immutable; otherwise refresh its prepared profile. */
    if(!ln_player_cancel_next())return false;
    prefetching=next_ready=next_armed=next_failed=false;
    if(resolver_kind==2)resolver_kind=0;
    profile=next;++revision;return true;
}
uint32_t ln_music_deadline(uint32_t now){
    if(selecting||have_waiting||resolver_kind||ln_music_browser_busy()||ln_music_search_busy()||ln_music_queue_view_busy())return now;
    uint32_t next=ln_player_deadline(now),library=ln_music_library_deadline(now);
    if((int32_t)(library-next)<0)next=library;
    uint32_t history=ln_music_history_deadline(now);
    if((int32_t)(history-next)<0)next=history;
    if(volume_retry_pending&&(int32_t)(volume_retry_at-next)<0)next=volume_retry_at;
    return next;
}
/* Menu rows map to stable service actions, shared by labels and selection. */
uint32_t ln_music_option_action(uint32_t row){
    /* Queue, playback settings, favorites/bookmarks, transport, stop. */
    static const uint8_t actions[]={7,0,1,8,2,3,4,5,9,10,6};
    return row<sizeof(actions)?actions[row]:UINT32_MAX;
}
uint32_t ln_music_queue_action(uint32_t row){
    /* Play, move up/down, remove, clear. */
    static const uint8_t actions[]={0,2,3,1,4};
    return row<sizeof(actions)?actions[row]:UINT32_MAX;
}
const char *ln_music_option_label(uint32_t index){
    const struct ln_music_journal_record *record=have_current?ln_music_history_get(current.track.id):0;
    if(index==2||index==3){
        if(ln_music_history_error())return "History unavailable";
        if(!ln_music_history_ready())return "History loading";
        if(have_current&&!ln_music_history_record_ready(current.track.id))return "History loading";
        if(have_current&&ln_music_history_record_error(current.track.id))
            return "History full";
    }
    switch(index){
    case 0:return queue.shuffled?"Shuffle: On":"Shuffle: Off";
    case 1:return queue.repeat==LINNET_QUEUE_REPEAT_ONE?"Repeat: One":queue.repeat==LINNET_QUEUE_REPEAT_ALL?"Repeat: All":"Repeat: Off";
    case 2:return !ln_music_history_ready()?"Favorite: Unavailable":record&&(record->flags&LN_MUSIC_JOURNAL_FAVORITE)?"Favorite: Yes":"Favorite: No";
    case 3:return record&&(record->flags&LN_MUSIC_JOURNAL_BOOKMARK)?"Update bookmark":"Save bookmark";
    case 4:return record&&(record->flags&LN_MUSIC_JOURNAL_BOOKMARK)?"Resume bookmark":"No bookmark saved";
    case 5:return "Restart track";
    case 6:return "Stop";
    case 7:return "Play queue";
    case 8:return "Sound settings";
    case 9:return "Back 10 seconds";
    case 10:return "Forward 10 seconds";
    default:return "";
    }
}
bool ln_music_option_select(uint32_t index){
    if(shutting_down||index>10)return false;
    if(index==7||index==8)return false; /* Runtime opens their native scenes. */
    if(index==9||index==10){
        struct ln_player_status p;ln_player_snapshot(&p);uint64_t position=ln_player_position(),delta=(uint64_t)p.rate*10u;
        uint64_t target=index==9?(position>delta?position-delta:0):position+delta;
        uint64_t total=p.frames?p.frames:have_current?current.track.frames:0;
        if(total&&target>=total)target=total?total-1:0;
        return p.rate&&ln_music_seek(target);
    }
    if(index==6){ln_music_stop();return true;}
    if(index<2){
        if(!queue.count||manual_next_pending||selecting||have_waiting||resolver_kind==1)return false;
        if(!ln_player_cancel_next()&&!ln_player_seek(ln_player_position()))return false;
        prefetching=next_ready=next_armed=next_failed=false;
        if(resolver_kind==2)resolver_kind=0;
        if(index==0)ln_queue_shuffle(&queue,!queue.shuffled);
        else (void)ln_queue_set_repeat(&queue,(queue.repeat+1u)%3u);
        current_cursor=queue.cursor;
        ++revision;return true;
    }
    if(!have_current||selecting||have_waiting)return false;
    const struct ln_music_journal_record *record=ln_music_history_get(current.track.id);
    bool accepted=false;
    if(index==2)accepted=ln_music_history_set_favorite(current.track.id,!(record&&(record->flags&LN_MUSIC_JOURNAL_FAVORITE)));
    else if(index==3)accepted=ln_music_history_set_bookmark(current.track.id,true,ln_player_position());
    else{
        if(index==4&&(!record||!(record->flags&LN_MUSIC_JOURNAL_BOOKMARK)))return false;
        uint64_t position=index==4?record->bookmark_frame:0;
        struct ln_player_status p;ln_player_snapshot(&p);
        if(p.phase==LN_PLAYER_IDLE){requested_position=position;active=true;accepted=select_index(current.index);}
        else accepted=ln_player_seek(position);
        if(accepted){prefetching=next_ready=next_armed=next_failed=false;queue.position_samples=position;}
    }
    if(accepted)++revision;return accepted;
}
static bool select_queue(const struct ln_music_browser_queue *selection){
    uint8_t identity[32];uint32_t count=ln_music_library_count();
    if(shutting_down||!selection->count||selection->count>LINNET_QUEUE_SOURCE_MAX||
       selection->cursor>=selection->count||!ln_music_library_identity(identity)||
       !same(identity,selection->library_hash))return false;
    struct ln_queue replacement;ln_queue_init(&replacement,ln_time_us());
    replacement.volume_db_tenths=queue.volume_db_tenths;replacement.repeat=queue.repeat;
    for(uint32_t i=0;i<32;++i)replacement.library_identity[i]=identity[i];
    if(selection->source){
        if((selection->source==LN_QUEUE_ALL&&selection->count!=count)||
           (selection->source==LN_QUEUE_GROUP&&selection->source_group>=ln_music_library_group_count())||
           !ln_queue_set_source(&replacement,selection->source,selection->source_group,selection->count,selection->cursor))return false;
    }else{
        if(selection->count>LINNET_QUEUE_CAPACITY)return false;
        for(uint32_t i=0;i<selection->count;++i)
            if(selection->tracks[i]>=count||!ln_queue_add(&replacement,selection->tracks[i]))return false;
        if(!ln_queue_select_occurrence(&replacement,selection->cursor))return false;
    }
    ln_queue_shuffle(&replacement,queue.shuffled);
    remember_position();queue=replacement;++revision;skipped=0;active=true;requested_position=0;
    return select_current();
}
bool ln_music_select(uint32_t index){
    struct ln_music_browser_queue selection={0};selection.count=1;selection.tracks[0]=index;
    if(!ln_music_library_identity(selection.library_hash))return false;
    return select_queue(&selection);
}
bool ln_music_next(bool previous){
    if(shutting_down)return false;
    remember_position();
    bool moved=previous?ln_queue_previous(&queue):ln_queue_next(&queue,true);
    uint32_t index;if(!moved||!ln_queue_current(&queue,&index))return false;
    ++revision;active=true;skipped=0;requested_position=0;
    if(!previous&&next_armed&&next_ordinal==index&&ln_player_skip_prepared_next(next_token)){
        manual_next_pending=true;return true;}
    bool accepted=select_current();
    if(accepted){
        /* An explicit skip no longer needs the old song's PCM runway. Stop
         * its producer promptly; the player still drains its admitted read
         * before replacement metadata/audio can take storage ownership. */
        struct ln_player_status player;ln_player_snapshot(&player);
        if(player.phase!=LN_PLAYER_IDLE&&player.phase!=LN_PLAYER_STOPPING)
            ln_player_stop_for_restart();
    }
    return accepted;
}
void ln_music_toggle(void){
    if(shutting_down)return;
    struct ln_player_status p;ln_player_snapshot(&p);
    if(ln_player_toggle_pause())return;
    if(p.phase==LN_PLAYER_IDLE&&!selecting&&!have_waiting&&!resolver_kind){
        if(queue.count){requested_position=queue.position_samples;active=true;(void)select_current();}}
}
static void remember_position(void){
    uint32_t index;struct ln_player_status p;ln_player_snapshot(&p);
    if(have_current&&!selecting&&!have_waiting&&!manual_next_pending&&resolver_kind!=1&&ln_queue_current(&queue,&index)&&current_cursor==queue.cursor&&p.generation&&
       p.phase!=LN_PLAYER_IDLE&&p.phase!=LN_PLAYER_ERROR&&p.phase!=LN_PLAYER_STOPPING){
        uint64_t position=ln_player_position();
        (void)ln_music_history_set_resume(current.track.id,true,position);
        if(position!=queue.position_samples){queue.position_samples=position;++revision;}}
}
void ln_music_stop(void){if(shutting_down)return;remember_position();active=false;have_waiting=false;selecting=false;resolver_kind=0;volume_retry_pending=false;volume_retry_at=0;discard_next(false);ln_player_stop();++revision;}
bool ln_music_seek(uint64_t frame){
    if(shutting_down||!ln_player_seek(frame))return false;
    prefetching=next_ready=next_armed=next_failed=false;
    if(resolver_kind==2)resolver_kind=0;
    queue.position_samples=frame;++revision;return true;
}
void ln_music_headphones(bool connected){
    if(shutting_down)return;
    if(headphone_known&&headphones&&!connected)(void)ln_player_pause(true);
    headphones=connected;headphone_known=true;
}
static bool persist(void){
    if(!restored||revision==saved_revision)return true;
    if(persist_failed||ln_storage_busy())return false;
    if(!ln_storage_prepared()){
        if(ln_storage_prepare_writes()<0)persist_failed=true;
        return false;
    }
    uint32_t snapshot_revision=revision,length=ln_music_settings_encode(&queue,&profile,resume,sizeof resume);
    if(!length)return false;
    if(!ln_display_settings_music(true,resume,&length)){persist_failed=true;return false;}
    if(revision==snapshot_revision)saved_revision=snapshot_revision;return true;
}
bool ln_music_prepare_shutdown(void){return ln_music_quiesce(true);}
bool ln_music_quiesce(bool save_settings){
    if(shutting_down||stepping||ln_storage_busy())return false;
    shutting_down=true;
    remember_position();ln_music_history_freeze();
    active=have_waiting=selecting=false;resolver_kind=0;
    ln_player_stop();ln_music_library_cancel();ln_music_art_request(0,0);
    uint32_t started=ln_time_us();bool drained=false;
    for(uint32_t budget=0;budget<1000000u;++budget){
        ln_player_step();ln_music_library_step();ln_music_art_step(false);
        struct ln_player_status p;struct ln_audio_status a;
        ln_player_snapshot(&p);ln_audio_snapshot(&a);
        if(p.phase==LN_PLAYER_ERROR||a.fault)return false;
        if(p.phase==LN_PLAYER_IDLE&&!a.playing&&!ln_storage_busy()&&
           ln_music_library_status()==LN_LIBRARY_CLOSED){drained=true;break;}
        if(ln_time_us()-started>=30000000u)return false;
    }
    if(!drained)return false;
    if(!save_settings)return true;
    if((restored&&revision!=saved_revision)||ln_music_history_dirty()){
        int writable;
        while((writable=ln_storage_prepare_writes())==0){
            ln_storage_step();if(ln_time_us()-started>=30000000u)return false;
        }
        if(writable<0)return false;
    }
    if(!persist())return false;
    /* No accepted history events exist before ready; shutdown must not start
     * a new load after closing the library. Crash recovery never calls here. */
    if(!ln_music_history_ready()){
        /* Fresh installations have no optional history banks. No history
         * events can be accepted before ready, so absence has nothing to
         * flush and must not prevent Sync or normal shutdown. */
        int error=ln_music_history_error();
        return error==LN_HISTORY_OK||error==LN_HISTORY_MISSING;
    }
    for(;;){
        int result=ln_music_history_flush();if(result)return result==1;
        if(ln_time_us()-started>=30000000u)return false;
        ln_music_history_step(true);
        ln_storage_step();
    }
}
void ln_music_volume(int32_t steps){
    if(shutting_down)return;
    int64_t next=(int64_t)queue.volume_db_tenths+(int64_t)steps*10;
    if(next<-730)next=-730;if(next>0)next=0;
    queue.volume_db_tenths=(int32_t)next;++revision;
    struct ln_audio_status audio;ln_audio_snapshot(&audio);
    if(audio.initialized){
        if(ln_audio_volume(queue.volume_db_tenths)){
            volume_retry_pending=false;volume_retry_at=0;
        }else{
            volume_retry_pending=true;volume_retry_at=ln_time_us()+LN_MUSIC_VOLUME_RETRY_US;
        }
    }else{volume_retry_pending=false;volume_retry_at=0;}
}
/* Shared output gain also runs while video owns the audio sink. */
void ln_music_volume_sync(void){
    if(shutting_down)return;
    struct ln_audio_status audio;ln_audio_snapshot(&audio);
    if(!audio.initialized){volume_retry_pending=false;volume_retry_at=0;}
    else if(audio.volume_db_tenths!=queue.volume_db_tenths){
        uint32_t retry_now=ln_time_us();
        if(!volume_retry_pending||(int32_t)(retry_now-volume_retry_at)>=0){
            if(ln_audio_volume(queue.volume_db_tenths)){
                volume_retry_pending=false;volume_retry_at=0;
            }else{
                volume_retry_pending=true;volume_retry_at=ln_time_us()+LN_MUSIC_VOLUME_RETRY_US;
            }
        }
    }else{volume_retry_pending=false;volume_retry_at=0;}
}
static void music_step(void){
    struct ln_player_status before,p;struct ln_audio_status audio;
    bool expected=false;
    if(active&&have_current&&!selecting&&!have_waiting&&!next_failed){
        if(next_armed||next_ready||prefetching||resolver_kind==2)expected=true;
        else {uint32_t cursor;expected=next_queue_cursor(&cursor);}
    }
    ln_player_expect_next(expected);
    ln_player_snapshot(&before);ln_player_step();ln_player_snapshot(&p);ln_audio_snapshot(&audio);
    struct ln_player_transition transition;
    if(ln_player_take_transition(&transition)&&next_armed){
        uint32_t index;
        if(transition.token!=next_token||(!transition.manual&&!ln_queue_next(&queue,false))||
           !ln_queue_current(&queue,&index)||index!=next_ordinal){ln_music_stop();return;}
        if(have_current&&!transition.manual){(void)ln_music_history_played(current.track.id);
            (void)ln_music_history_set_resume(current.track.id,false,0);}
        current=upcoming;current_cursor=queue.cursor;have_current=true;next_armed=next_ready=prefetching=next_failed=false;
        ln_music_history_pin_current(true,current.track.id);
        manual_next_pending=false;
        queue.position_samples=0;++revision;skipped=0;
        ln_music_art_request(current.art_path,current.art_crc);
    }
    /* A failed promotion has no transition event. Keep the requested queue
     * position, but clear its abandoned intent without completing the old song. */
    if(manual_next_pending&&(p.phase==LN_PLAYER_IDLE||p.phase==LN_PLAYER_ERROR)){
        manual_next_pending=next_armed=next_ready=prefetching=next_failed=false;
        active=false;ln_player_stop();++revision;
    }
    bool urgent=ln_player_prefetch_urgent();
    uint32_t read_runway=ln_player_background_frames(audio.rate);
    bool photo_priority=false;
#if defined(LINNET_PHOTOS)
    /* Release speculative-read priority before the audible tail, not only
     * after decode reaches EOF. Otherwise a photo/zoom can leave too little
     * runway to resolve the following short track's metadata. */
    uint64_t track_frames=p.frames?p.frames:current.track.frames;
    uint64_t position=ln_player_position();
    bool transition_soon=track_frames&&(position>=track_frames||
        track_frames-position<=(uint64_t)audio.rate*3u);
    photo_priority=active&&have_current&&!selecting&&!have_waiting&&!manual_next_pending&&
        p.phase==LN_PLAYER_PLAY&&!urgent&&!transition_soon&&ln_photos_busy();
#endif
    /* Both services use the same PCM reserve. Let unfinished visible photos
     * claim that window before speculative metadata consumes it repeatedly.
     * Library/history service calls still drain their admitted operations. */
    ln_music_library_pause(audio.initialized&&audio.playing&&!urgent&&
        (audio.queued<read_runway||photo_priority));
    ln_music_browser_suspend(queue_opened||ln_music_queue_view_busy()||ln_music_search_active());
    ln_music_library_window_enable(ln_music_browser_window_needed());
    ln_music_library_step();
    uint32_t resolved,token;
    if(ln_music_library_take_queue_member(&resolved,&token)&&resolver_kind&&token==resolver_token){
        uint32_t kind=resolver_kind;resolver_kind=0;
        if(resolved>=ln_music_library_count()){
            if(kind==1){active=false;ln_player_stop();}else next_failed=true;
        }else if(kind==1){
            uint32_t ordinal;if(ln_queue_current(&queue,&ordinal)&&ordinal==resolver_ordinal)(void)select_index(resolved);
        }else {next_index=resolved;prefetching=ln_music_library_prefetch(resolved);}
    }
    ln_music_browser_step();
    ln_music_search_step();
    if(queue_opened)ln_music_queue_view_update(&queue,revision);
    ln_music_queue_view_step(queue_opened&&!ln_music_search_active()&&ln_music_browser_query_idle());
    /* Fill cached labels before rendering, with a strict time/iteration budget.
     * Hardware waits and PCM pressure always return control to the executive. */
    uint32_t metadata_started=ln_time_us();
    for(uint32_t n=0;n<12u&&ln_music_library_can_continue();n++){
        if((uint32_t)(ln_time_us()-metadata_started)>=1000u)break;
        if(!ln_music_browser_busy()&&!ln_music_search_busy()&&!ln_music_queue_view_busy())break;
        ln_music_library_step();
        ln_music_browser_step();
        ln_music_search_step();
        ln_music_queue_view_step(queue_opened&&!ln_music_search_active()&&ln_music_browser_query_idle());
    }
    struct ln_music_browser_queue browser_queue;
    if(ln_music_search_take_queue(&browser_queue)&&select_queue(&browser_queue)){
        ln_music_search_close();show_now_playing=true;
    }
    if(ln_music_browser_take_queue(&browser_queue)&&select_queue(&browser_queue))show_now_playing=true;
    ln_music_art_step(!audio.initialized||!audio.playing||audio.queued>=LINNET_AUDIO_RING_FRAMES-2048u);
    if(!restored&&ln_music_library_status()==LN_LIBRARY_READY&&!ln_storage_busy()&&
       (!restore_attempts||(int32_t)(ln_time_us()-restore_retry_at)>=0)){
        /* A user edit made while waiting wins over the older saved queue. */
        if(revision!=restore_revision||active||selecting||have_waiting||resolver_kind==1){restored=true;}
        else {
            uint8_t identity[32];uint32_t length=sizeof resume,snapshot_revision=revision;
            int result=ln_music_library_identity(identity)?ln_display_settings_music_restore(resume,&length):0;
            if(result==0&&revision==restore_revision&&!active&&!selecting&&!have_waiting&&resolver_kind!=1){
                if(++restore_attempts<3u)restore_retry_at=ln_time_us()+1000000u;
                else {
                    /* Do not publish fallback defaults over an unread queue.
                     * Subsequent user changes can still be saved normally. */
                    restored=true;saved_revision=revision;
                }
            }else {
                if(result==1){
                    struct ln_queue saved;struct ln_music_profile saved_profile;
                    if(ln_music_settings_decode(&saved,&saved_profile,resume,length)&&revision==snapshot_revision&&revision==restore_revision&&!active&&!selecting&&!have_waiting&&resolver_kind!=1){
                        profile=saved_profile;
                        bool valid=true;
                        if(!same(saved.library_identity,identity))valid=false;
                        if(saved.source==LN_QUEUE_ALL)valid=valid&&saved.source_count==ln_music_library_count();
                        else if(saved.source==LN_QUEUE_GROUP)valid=valid&&saved.source_group<ln_music_library_group_count();
                        else for(uint32_t i=0;i<saved.count;++i)if(saved.tracks[i]>=ln_music_library_count())valid=false;
                        if(valid&&revision==snapshot_revision&&revision==restore_revision&&!active&&!selecting&&!have_waiting&&resolver_kind!=1){queue=saved;profile=saved_profile;}
                    }
                }
                restored=true;
            }
        }
    }
    if(ln_music_library_take_selection(&waiting)){have_waiting=selecting;selecting=false;if(have_waiting)ln_player_stop_for_restart();}
    if(next_armed&&p.next_phase==LN_PLAYER_NEXT_FAILED){
        (void)ln_player_cancel_next();next_armed=next_ready=false;next_failed=true;
    }
    if(have_waiting&&ln_music_history_ready()&&!ln_music_history_record_ready(waiting.track.id))
        (void)ln_music_history_prefetch(waiting.track.id);
    if(have_waiting&&p.phase==LN_PLAYER_IDLE&&!ln_storage_busy()&&
       (ln_music_history_error()||(ln_music_history_ready()&&
        (ln_music_history_record_ready(waiting.track.id)||ln_music_history_record_error(waiting.track.id))))){
        struct ln_dsp_config dsp;
        if(!ln_music_profile_configure(&profile,waiting.track.rate,waiting.track.replaygain,&dsp)){
            have_waiting=false;active=false;notice="Unsupported sample rate";ln_player_stop();++revision;
        }else if(ln_player_open_configured(waiting.path,waiting.track.file_bytes,requested_position,&dsp,waiting.track.rate)){
            current=waiting;current_cursor=waiting_cursor;have_current=true;have_waiting=false;
            ln_music_history_pin_current(true,current.track.id);
            ln_music_art_request(current.art_path,current.art_crc);
            active=true;queue.position_samples=requested_position;requested_position=0;++revision;
        }
    }else if(active&&!have_waiting&&!selecting&&resolver_kind!=1&&!next_armed&&before.phase!=LN_PLAYER_IDLE&&before.phase!=LN_PLAYER_ERROR&&
              (p.phase==LN_PLAYER_IDLE||p.phase==LN_PLAYER_ERROR)){
        if(p.phase==LN_PLAYER_ERROR){++skipped;ln_player_stop();}
        else {
            if(have_current){(void)ln_music_history_played(current.track.id);
                (void)ln_music_history_set_resume(current.track.id,false,0);}
            /* A completed final item must restart at its beginning, including
             * after a previously persisted pause or seek within that item. */
            if(queue.position_samples||requested_position){
                queue.position_samples=requested_position=0;++revision;
            }
        }
        uint32_t index;
        if(skipped<LINNET_QUEUE_CAPACITY&&ln_queue_next(&queue,false)&&ln_queue_current(&queue,&index)){
            /* A pending next-member lookup must not swallow this terminal
             * edge. select_current replaces it with a fresh selection token;
             * the library drains any superseded reader before reusing it. */
            requested_position=0;(void)select_current();++revision;
        }else active=false;
    }
    struct ln_music_library_row prefetched;
    if(ln_music_library_take_prefetch(&prefetched)&&prefetching&&prefetched.index==next_index){
        upcoming=prefetched;prefetching=false;next_ready=true;
    }
    if(active&&have_current&&!selecting&&!have_waiting&&!next_failed){
        if(!prefetching&&!next_ready&&!next_armed&&!resolver_kind){
            uint32_t cursor;
            if(next_queue_cursor(&cursor)&&ln_queue_track_at(&queue,cursor,&next_ordinal))
                (void)resolve_queue(next_ordinal,2);
        }
        if(next_ready&&!next_armed&&!photo_priority&&(p.phase==LN_PLAYER_PRIME||p.phase==LN_PLAYER_PLAY||p.phase==LN_PLAYER_DRAIN)){
            uint32_t candidate=next_token+1u;if(!candidate)candidate=1;
            struct ln_dsp_config dsp;
            if(!ln_music_history_error()&&ln_music_history_ready()&&!ln_music_history_record_ready(upcoming.track.id)&&!ln_music_history_record_error(upcoming.track.id)){
                (void)ln_music_history_prefetch(upcoming.track.id);
            }else if(!ln_music_profile_configure(&profile,upcoming.track.rate,upcoming.track.replaygain,&dsp)){
                next_ready=false;next_failed=true;
            }else if(ln_player_prepare_next_configured(upcoming.path,upcoming.track.file_bytes,candidate,&dsp,upcoming.track.rate)){
                next_token=candidate;next_armed=true;}
        }
    }
    if(p.phase!=LN_PLAYER_PAUSE)pause_captured=false;
    if(p.phase==LN_PLAYER_PAUSE&&!audio.playing&&!pause_captured){
        remember_position();pause_captured=ln_music_history_ready()||ln_music_history_error()!=0;
    }
    bool changing=manual_next_pending||selecting||have_waiting||resolver_kind==1;
    bool stopped=!audio.playing&&(p.phase==LN_PLAYER_PAUSE||p.phase==LN_PLAYER_IDLE||p.phase==LN_PLAYER_ERROR);
    bool may_write=stopped&&!changing;
    /* Explicit selection can pass briefly through IDLE. Preserve history
     * loading and an already-started publication, but do not start optional
     * writes ahead of the replacement track's metadata and audio reads. */
    /* Finish an admitted page publication at the normal background reserve.
     * Waiting for a full ring again after its write can strand FLUSH and block
     * the following track's history lookup. Only FLUSH/CHECK/ACK apply;
     * returning to IDLE restores the stricter threshold for each new write. */
    bool history_headroom=(stopped||(audio.playing&&
        (audio.queued>=LINNET_AUDIO_RING_FRAMES-2048u||
         (ln_music_history_finishing()&&audio.queued>=read_runway))))&&
        (!changing||!ln_music_history_ready()||ln_music_history_busy());
    bool history_read=stopped||(!audio.playing&&p.phase==LN_PLAYER_PRIME)||urgent||
        (audio.playing&&audio.queued>=read_runway&&!photo_priority);
    ln_music_history_service(history_read,history_headroom,audio.playing);
    ln_music_volume_sync();
    /* Durability work is deferred until playback is stopped/paused and the
     * asynchronous media owner has drained. New UI input may supersede this
     * snapshot while storage progress runs; retain its dirty revision then. */
    if(restored&&!persist_failed&&revision!=saved_revision&&!ln_storage_busy()&&
       may_write&&!manual_next_pending&&!selecting&&!have_waiting&&resolver_kind!=1){
        (void)persist();
    }
}

void ln_music_step(void){
    if(shutting_down||stepping)return;
    stepping=true;music_step();stepping=false;
}
