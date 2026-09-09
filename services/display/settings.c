#include "settings.h"
#include "services/storage/storage.h"
#include "boot/include/linnet_boot.h"
#include "ui/runtime/ui.h"
static const uint32_t seconds[]={0,5,10,15,30,60,120};
static const char *const labels[]={"Timeout: Never","Timeout: 5 seconds","Timeout: 10 seconds","Timeout: 15 seconds","Timeout: 30 seconds","Timeout: 1 minute","Timeout: 2 minutes"};
static uint32_t choice=4,revision,record_revision,battery_capacity=1200;
static uint32_t theme_index=UINT32_MAX,theme_revision;
static bool theme_loaded,theme_dirty,theme_available;
static bool step_busy;
static char battery_label[25];
static char update_labels[5][32];
static uint32_t update_history;
static uint32_t update_snapshot[16];
static bool update_known;
static bool loaded,dirty,clock_12;
static uint8_t photo_resume[16];
static uint32_t video_resume[2];
static uint32_t get(const uint8_t*p){return(uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put(uint8_t*p,uint32_t v){for(uint32_t i=0;i<4;++i)p[i]=(uint8_t)(v>>(i*8));}
void ln_display_settings_init(void){clock_12=false;update_known=false;for(uint32_t i=0;i<5;++i)update_labels[i][0]=0;battery_capacity=1200;choice=4;video_resume[0]=video_resume[1]=0;revision=record_revision=0;loaded=dirty=false;theme_index=UINT32_MAX;theme_revision=0;theme_loaded=theme_dirty=theme_available=step_busy=false;for(uint32_t i=0;i<16;++i)photo_resume[i]=0;}
bool ln_display_clock_12(void){return clock_12;}
void ln_display_clock_toggle(void){clock_12=!clock_12;dirty=true;++revision;++record_revision;}
uint32_t ln_display_backlight_timeout_us(void){return seconds[choice]*1000000u;}
uint32_t ln_display_settings_revision(void){return revision;}
uint32_t ln_display_theme_index(void){return theme_index;}
uint32_t ln_display_theme_revision(void){return theme_revision;}
__attribute__((weak)) bool ln_display_theme_presented(uint32_t value){(void)value;return false;}
bool ln_display_theme_set(uint32_t index){
    if((index!=UINT32_MAX&&index>=ln_ui_theme_count)||index==theme_index)return false;
    theme_index=index;theme_dirty=true;++theme_revision;++revision;return true;
}
const char *ln_display_theme_status(void){
    if(theme_index==UINT32_MAX&&!theme_dirty)return "Default";
    return theme_available?(theme_dirty?"Saving...":"Saved"):"This session";
}
bool ln_display_settings_pending(void){return dirty||(theme_dirty&&(!theme_loaded||theme_available));}
const char *ln_display_settings_label(void){return labels[choice];}
bool ln_display_settings_adjust(int32_t direction){
    if(!direction)return false;
    choice=direction<0?(choice?choice-1u:6u):(choice==6u?0u:choice+1u);
    dirty=true;++revision;++record_revision;return true;
}
uint32_t ln_battery_capacity_mah(void){return battery_capacity;}
const char *ln_battery_capacity_label(void){
    const char *prefix="Battery: ";uint32_t at=0,n=battery_capacity,digits=0;char reverse[5];
    while(*prefix)battery_label[at++]=*prefix++;
    do{reverse[digits++]=(char)('0'+n%10u);n/=10u;}while(n);
    while(digits)battery_label[at++]=reverse[--digits];
    prefix=" mAh";while(*prefix)battery_label[at++]=*prefix++;battery_label[at]=0;return battery_label;
}
bool ln_battery_capacity_adjust(int32_t direction){
    if(!direction||(direction<0&&battery_capacity==50u)||(direction>0&&battery_capacity==10000u))return false;
    battery_capacity=direction<0?battery_capacity-50u:battery_capacity+50u;
    dirty=true;++revision;++record_revision;return true;
}
/* LDS5 adds the clock format at byte 7 to LDS4 capacity/music layout. Its 36-byte
 * overhead leaves 444 bytes for the existing maximum music payload. */
static bool valid_photo(const uint8_t *resume){
    uint32_t flags=get(resume+8);
    return get(resume+4)<=65535u&&(flags&255u)<=5u&&((flags>>8)&255u)<=3u&&(flags>>16)<=2u;
}
static int read_record(uint8_t raw[480],uint32_t *offset,uint32_t *length){
    uint32_t bytes=480;
    if(ln_storage_busy()||!ln_storage_mounted()||!ln_storage_settings(false,raw,&bytes))return 0;
    if(bytes>480)return -1;
    uint32_t out_offset=0,out_length=bytes,saved_choice=choice,saved_capacity=1200;bool saved_clock_12=false;
    uint8_t saved_photo[16]={0};uint32_t saved_video[2]={0};
    uint32_t magic=bytes>=4?get(raw):0;
    bool envelope=magic==0x3153444cu||magic==0x3253444cu||magic==0x3353444cu||(magic==0x3453444cu||magic==0x3553444cu);
    if(envelope){
        bool compact=magic==0x3353444cu||(magic==0x3453444cu||magic==0x3553444cu);
        uint32_t overhead=magic==0x3153444cu?16u:((magic==0x3453444cu||magic==0x3553444cu)?36u:32u);
        if(bytes<overhead||get(raw+bytes-4)!=ln_crc32(raw,bytes-4))return -1;
        uint32_t n=compact?(uint32_t)raw[4]|((uint32_t)raw[5]<<8):get(raw+4);
        if(n!=bytes-overhead)return -1;
        saved_choice=7;
        if(compact){
            uint32_t f=raw[14];
            if((magic==0x3553444cu?raw[7]>1u:raw[7]!=0u)||raw[6]>6||raw[15]||(f&7u)>5||((f>>5)&3u)>2||(f&128u))return -1;
            saved_choice=raw[6];saved_clock_12=magic==0x3553444cu&&raw[7]==1u;
            put(saved_photo,get(raw+8));put(saved_photo+4,(uint32_t)raw[12]|((uint32_t)raw[13]<<8));
            put(saved_photo+8,(f&7u)|(((f>>3)&3u)<<8)|(((f>>5)&3u)<<16));put(saved_photo+12,get(raw+16));
            saved_video[0]=get(raw+20);saved_video[1]=get(raw+24);
        }else{
            for(uint32_t i=0;i<7;++i)if(seconds[i]==get(raw+8))saved_choice=i;
            if(magic==0x3253444cu)for(uint32_t i=0;i<16;++i)saved_photo[i]=raw[12+i];
        }
        if(saved_choice==7||!valid_photo(saved_photo))return -1;
        if((magic==0x3453444cu||magic==0x3553444cu)){
            saved_capacity=get(raw+28);
            if(saved_capacity<50u||saved_capacity>10000u||saved_capacity%50u)return -1;
        }
        out_offset=overhead-4;out_length=bytes-overhead;
    }
    /* Commit only after the complete envelope has passed validation. */
    if(!loaded){
        if(!dirty&&(choice!=saved_choice||battery_capacity!=saved_capacity||clock_12!=saved_clock_12)){
            choice=saved_choice;battery_capacity=saved_capacity;clock_12=saved_clock_12;++revision;
        }
        for(uint32_t i=0;i<16;++i)photo_resume[i]=saved_photo[i];
        video_resume[0]=saved_video[0];video_resume[1]=saved_video[1];
    }
    *offset=out_offset;*length=out_length;loaded=true;return 1;
}
static int write_record(uint8_t raw[480],const uint8_t *data,uint32_t length){
    if(length>444||!valid_photo(photo_resume)||battery_capacity<50u||battery_capacity>10000u||battery_capacity%50u)return 0;
    for(uint32_t i=length;i;--i)raw[32+i-1]=data[i-1];
    uint32_t index=get(photo_resume+4),flags=get(photo_resume+8);
    if(index>65535u||(flags&255u)>5u||((flags>>8)&255u)>3u||(flags>>16)>2u)return 0;
    put(raw,0x3553444cu);raw[4]=(uint8_t)length;raw[5]=(uint8_t)(length>>8);raw[6]=(uint8_t)choice;raw[7]=clock_12?1u:0u;
    put(raw+8,get(photo_resume));raw[12]=(uint8_t)index;raw[13]=(uint8_t)(index>>8);
    raw[14]=(uint8_t)((flags&7u)|(((flags>>8)&3u)<<3)|(((flags>>16)&3u)<<5));raw[15]=0;
    put(raw+16,get(photo_resume+12));put(raw+20,video_resume[0]);put(raw+24,video_resume[1]);
    put(raw+28,battery_capacity);put(raw+32+length,ln_crc32(raw,32+length));
    uint32_t bytes=length+36,version=record_revision;
    if(!ln_storage_settings(true,raw,&bytes))return 0;
    if(record_revision==version)dirty=false;return 1;
}
bool ln_display_settings_photo_get(uint8_t out[16]){
    if(!loaded||!out)return false;
    for(uint32_t i=0;i<16;++i)out[i]=photo_resume[i];return true;
}
void ln_display_settings_photo_set(const uint8_t in[16]){
    if(!loaded||!in)return;bool changed=false;
    for(uint32_t i=0;i<16;++i)if(photo_resume[i]!=in[i])changed=true;
    if(!changed)return;
    for(uint32_t i=0;i<16;++i)photo_resume[i]=in[i];dirty=true;++record_revision;
}
bool ln_display_settings_video_get(uint32_t out[2]){
    if(!loaded||!out)return false;out[0]=video_resume[0];out[1]=video_resume[1];return true;
}
void ln_display_settings_video_set(const uint32_t in[2]){
    if(!loaded||!in||(in[0]==video_resume[0]&&in[1]==video_resume[1]))return;
    video_resume[0]=in[0];video_resume[1]=in[1];dirty=true;++record_revision;
}
int ln_display_settings_music_restore(uint8_t *data,uint32_t *length){
    if(!data||!length)return -1;
    uint8_t raw[480];uint32_t offset,bytes;
    int result=read_record(raw,&offset,&bytes);if(result!=1)return result;
    if(*length<bytes)return -1;
    for(uint32_t i=0;i<bytes;++i)data[i]=raw[offset+i];
    *length=bytes;return 1;
}
int ln_display_settings_music(bool write,uint8_t *data,uint32_t *length){
    if(!data||!length)return 0;
    uint8_t raw[480];uint32_t offset,bytes;
    if(read_record(raw,&offset,&bytes)!=1)return 0;
    if(write)return write_record(raw,data,*length);
    if(*length<bytes)return 0;
    for(uint32_t i=0;i<bytes;++i)data[i]=raw[offset+i];
    *length=bytes;return 1;
}
/* Theme sidecars are independent of the settings/music envelope.
 * Optional or invalid sidecars never block shutdown. */
static bool theme_id_char(uint8_t c){return (c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='.'||c=='-';}
static bool theme_id_valid(const uint8_t *id,uint32_t length){
    if(!length)return true;
    bool start=true,dot=false;
    for(uint32_t i=0;i<length;++i){uint8_t c=id[i];
        if(start){if(c<'a'||c>'z')return false;start=false;}
        else if(c=='.'){start=true;dot=true;}
        else if(!theme_id_char(c))return false;
    }
    return dot&&!start;
}
static void theme_step(bool presented,uint32_t presented_revision,bool flush){
    uint8_t payload[96];uint32_t length=sizeof(payload);
    if(!theme_loaded){
        int result=ln_storage_theme(false,payload,&length);
        if(!result)return;
        theme_loaded=true;theme_available=result==1;
        uint32_t saved=UINT32_MAX;
        if(theme_available&&length){
            if(length<9u||length>89u||get(payload)!=0x3148544cu||get(payload+4)!=1u||payload[length-1])theme_available=false;
            if(theme_available){
                if(!theme_id_valid(payload+8,length-9u))theme_available=false;
            }
            if(theme_available&&length>9u){
                for(uint32_t i=0;i<ln_ui_theme_count;++i){
                    const char *id=ln_ui_themes[i].id;uint32_t at=0;
                    while(at<length-9u&&id[at]&&(uint8_t)id[at]==payload[8+at])++at;
                    if(at==length-9u&&!id[at]){saved=i;break;}
                }
            }
        }
        if(!theme_dirty)theme_index=saved;
        ++revision;
    }
    if(!theme_dirty)return;
    if(!theme_available){theme_dirty=false;++revision;return;}
    /* Loading and write preparation may run nested input callbacks. A token
     * for their former selection must not authorize the new selection. */
    if(!flush&&(!presented||theme_revision!=presented_revision))return;
    /* Recovery may have closed the stores since this owner loaded its value.
     * Reopen them through a read before the final frame check, so callbacks in
     * open_stores/theme_open cannot invalidate readiness inside publication. */
    length=sizeof(payload);int probe=ln_storage_theme(false,payload,&length);
    if(!probe)return;
    if(probe<0){theme_available=theme_dirty=false;++revision;return;}
    if(!flush&&(!presented||theme_revision!=presented_revision||
       !ln_display_theme_presented(presented_revision)))return;
    const char *id=theme_index==UINT32_MAX?"":ln_ui_themes[theme_index].id;
    uint32_t count=0;while(id[count]&&count<80u&&theme_id_char((uint8_t)id[count]))++count;
    if(id[count]){theme_available=false;theme_dirty=false;++revision;return;}
    put(payload,0x3148544cu);put(payload+4,1);
    for(uint32_t i=0;i<count;++i)payload[8+i]=(uint8_t)id[i];payload[8+count]=0;
    length=9u+count;uint32_t version=theme_revision;
    int result=ln_storage_theme(true,payload,&length);
    if(result<0){theme_available=false;theme_dirty=false;++revision;}
    else if(result==1&&version==theme_revision){theme_dirty=false;++revision;}
}
static void settings_work(bool may_write,bool presented,uint32_t presented_revision,bool flush){
    if(!may_write||((loaded&&!dirty)&&(theme_loaded&&!theme_dirty))||ln_storage_busy()||!ln_storage_mounted())return;
    /* Once loading is complete, a theme waiting for its first frame must not
     * start disk write preparation. Independent LDS4 work may still proceed. */
    if(loaded&&!dirty&&theme_loaded&&theme_dirty&&!flush&&
       (!presented||theme_revision!=presented_revision))return;
    /* Discovery is complete once mounted; absent optional records need no write
     * preparation and cannot hold shutdown waiting for required state files. */
    if(!theme_loaded&&(ln_storage_capacity(LN_STORAGE_THEME0)!=512u||ln_storage_capacity(LN_STORAGE_THEME1)!=512u)){
        theme_loaded=true;theme_available=theme_dirty=false;++revision;
    }
    if(!ln_storage_prepared()&&ln_storage_prepare_writes()!=1)return;
    theme_step(presented,presented_revision,flush);
    if(loaded&&!dirty)return;
    uint8_t raw[480];uint32_t offset,bytes;
    if(read_record(raw,&offset,&bytes)!=1||!dirty||!may_write)return;
    /* Preparation can yield to other owners; re-read before publication. */
    if(read_record(raw,&offset,&bytes)!=1)return;
    (void)write_record(raw,raw+offset,bytes);
}
static void settings_step(bool may_write,bool presented,uint32_t presented_revision,bool flush){
    if(step_busy)return;
    step_busy=true;settings_work(may_write,presented,presented_revision,flush);step_busy=false;
}
void ln_display_settings_step_ready(bool may_write,bool theme_presented,uint32_t presented_revision){
    settings_step(may_write,theme_presented,presented_revision,false);
}
/* Terminal shutdown/Sync flush only: caller has stopped interactive rendering.
 * Normal runtime must use step_ready with an acknowledged frame revision. */
void ln_display_settings_step(bool may_write){settings_step(may_write,true,theme_revision,true);}
static void update_text(char out[32],const char *prefix,const char *value){
    uint32_t at=0;while(*prefix&&at<31)out[at++]=*prefix++;
    while(*value&&at<31)out[at++]=*value++;out[at]=0;
}
bool ln_display_update_status(const char *build,const uint32_t state[16],uint32_t history){
    if(!build||!state)return false;bool changed=!update_known||history!=update_history;
    for(uint32_t i=0;i<16;++i)if(update_snapshot[i]!=state[i])changed=true;
    if(!changed)return false;
    for(uint32_t i=0;i<16;++i)update_snapshot[i]=state[i];
    char short_id[13];uint32_t n=0;while(n<12&&build[n]){short_id[n]=build[n];++n;}short_id[n]=0;
    update_text(update_labels[0],"Build: ",short_id);
    update_text(update_labels[1],"Saved OS: ",!state[1]||!state[2]?"unavailable":state[5]==0?"slot A":state[5]==1?"slot B":"none");
    const char *candidate=!state[1]||!state[2]?"unavailable":state[11]?"uploading":state[6]>1?"none":state[7]?(state[6]==0?"slot A checking":"slot B checking"):state[6]==0?"slot A staged":"slot B staged";
    update_text(update_labels[2],"Update: ",candidate);
    if(state[15]){
        char digits[11];uint32_t value=state[15],count=0;char reverse[10];
        do{reverse[count++]=(char)('0'+value%10u);value/=10u;}while(value);
        for(uint32_t i=0;i<count;++i)digits[i]=reverse[count-1-i];digits[count]=0;
        update_text(update_labels[3],"Storage error: ",digits);
    }else update_text(update_labels[3],"Storage: ",state[14]?"recovery needed":!state[1]||!state[2]?"unavailable":"ready");
    const char *last=history==UINT32_MAX?"unavailable":history==0?"none recorded":
        (history&255u)==1u?((history>>8)==0?"A not confirmed":"B not confirmed"):
        ((history>>8)==0?"A failed checks":"B failed checks");
    update_text(update_labels[4],"Last: ",last);update_history=history;
    update_known=true;return true;
}
static bool text_equal(const char *a,const char *b){if(!a)return false;while(*a&&*a==*b){++a;++b;}return *a==*b;}
const char *ln_display_settings_text(const struct ln_ui_node*n,uint32_t item,const char*fallback){
    if(n->kind==LN_UI_TEXT&&update_known){
        static const char *const keys[]={"Update build","Update saved","Update candidate","Update health","Update history"};
        for(uint32_t i=0;i<5;++i)if(text_equal(n->text,keys[i]))return update_labels[i];
    }
    if(n->kind==LN_UI_VIRTUAL_LIST&&item==0&&n->text){
        const char *a=n->text,*b="Display timeout";while(*a&&*a==*b){++a;++b;}
        if(!*a&&!*b)return ln_display_settings_label();
        a=n->text;b="Battery capacity";while(*a&&*a==*b){++a;++b;}
        if(!*a&&!*b)return ln_battery_capacity_label();
    }
    return fallback;
}
