#include "boot/include/linnet_bytes.h"
#include "settings.h"
#include "services/storage/storage.h"
#include "hal/api/platform.h"
#include "boot/include/linnet_boot.h"
#include "ui/runtime/ui.h"
#include "services/games/games.h"
#include "linnet_build.h"
#include "hal/api/ata.h"
/* Append Off so existing saved timeout choices retain their meaning. */
enum { BACKLIGHT_OFF=7 };
static const uint32_t seconds[]={0,5,10,15,30,60,120,0};
static const char *const labels[]={"Backlight: Always on","Backlight: 5 sec","Backlight: 10 sec","Backlight: 15 sec","Backlight: 30 sec","Backlight: 1 minute","Backlight: 2 minutes","Backlight: Off"};
static const uint32_t shutdown_seconds[]={0,60,120,300,600,900,1800,3600,7200};
static const char *const shutdown_labels[]={"Off","1 min","2 min","5 min","10 min","15 min","30 min","1 hour","2 hours"};
static uint8_t shutdown_choice[2];
static char shutdown_label[2][32];
static uint32_t choice=4,revision,record_revision,battery_capacity=1200;
/* SETT bits 6..7: 0 Classic (also the legacy default), 1 Off, 2 Low, 3 High. */
static uint8_t click_tone;
static bool click_fallback_ready,click_changed;
static const char *const click_labels[]={"Clicker: Classic","Clicker: Off","Clicker: Low","Clicker: High"};
static uint32_t theme_index=UINT32_MAX,theme_revision;
static bool theme_loaded,theme_dirty,theme_available;
static uint16_t game_best[LN_GAME_COUNT];
extern void ln_games_best_set(uint32_t index,uint16_t value);
static bool menus_loaded;
static uint32_t menus_phase;
static uint8_t menus_data[80];
static struct ln_fat32_file menus_file;
static bool games_loaded;
static uint32_t games_phase;
static uint8_t games_data[12];
static struct ln_fat32_file games_file;
static bool about_loaded;
static uint32_t about_phase,about_count,about_percent;
static uint8_t about_data[1024];
static struct ln_fat32_file about_file;
static char about_build[20];
static char about_version[40];
static bool about_ata_ready;
static uint32_t about_ata_count;
static char about_ata_rows[8][64];
extern void ln_games_configure(uint16_t mask);
bool ln_display_settings_boot_ready(void){return theme_loaded&&menus_loaded&&games_loaded&&about_loaded;}
static bool step_busy;
static char battery_label[25];
static char update_labels[5][32];
static uint32_t update_history;
static uint32_t update_snapshot[16];
static bool update_known;
static bool loaded,dirty,clock_12;
static uint8_t photo_resume[16];
static uint32_t video_resume[2];
static uint8_t video_options;
static uint32_t record_first_dirty_at,record_last_dirty_at;
static void mark_record_dirty(void){
    uint32_t now=ln_time_us();
    if(!dirty)record_first_dirty_at=now;
    record_last_dirty_at=now;dirty=true;++record_revision;
}
static bool record_publish_due(void){
    uint32_t now=ln_time_us();
    return now-record_last_dirty_at>=500000u||now-record_first_dirty_at>=2000000u;
}
#if !defined(LINNET_PROFILE_RELEASE)
static uint32_t record_publishes,theme_publishes;
void ln_display_settings_diagnostics(uint32_t words[8]){
    words[0]=0x50544553u;words[1]=revision;words[2]=record_revision;words[3]=theme_revision;
    words[4]=record_publishes;words[5]=theme_publishes;
    words[6]=(dirty?1u:0u)|(theme_dirty?2u:0u);
    words[7]=(loaded?1u:0u)|(theme_loaded?2u:0u);
}
#endif
void ln_display_settings_init(void){menus_loaded=false;menus_phase=0;games_loaded=false;games_phase=0;about_loaded=false;about_phase=about_count=about_percent=0;about_ata_ready=false;about_ata_count=0;for(uint32_t i=0;i<LN_GAME_COUNT;++i)game_best[i]=0;shutdown_choice[0]=shutdown_choice[1]=0;clock_12=false;update_known=false;for(uint32_t i=0;i<5;++i)update_labels[i][0]=0;battery_capacity=1200;choice=4;click_tone=0;click_fallback_ready=click_changed=false;video_resume[0]=video_resume[1]=0;video_options=8u;revision=record_revision=0;loaded=dirty=false;record_first_dirty_at=record_last_dirty_at=0;theme_index=UINT32_MAX;theme_revision=0;theme_loaded=theme_dirty=theme_available=step_busy=false;for(uint32_t i=0;i<16;++i)photo_resume[i]=0;
    const char *build=LINNET_BUILD_ID;const char *prefix="Build ";uint32_t at=0;
    while(*prefix&&at<sizeof about_build-1u)about_build[at++]=*prefix++;
    for(uint32_t i=0;i<12u&&build[i]&&at<sizeof about_build-1u;++i)about_build[at++]=build[i];
    about_build[at]=0;
    const char *version=LINNET_SYSTEM_VERSION;prefix="Linnet OS ";at=0;
    while(*prefix&&at<sizeof about_version-1u)about_version[at++]=*prefix++;
    while(*version&&at<sizeof about_version-1u)about_version[at++]=*version++;
    about_version[at]=0;
#if !defined(LINNET_PROFILE_RELEASE)
    record_publishes=theme_publishes=0;
#endif
}
bool ln_display_clock_12(void){return clock_12;}
void ln_display_clock_toggle(void){clock_12=!clock_12;mark_record_dirty();++revision;}
uint32_t ln_display_backlight_timeout_us(void){return seconds[choice]*1000000u;}
bool ln_display_backlight_off(void){return choice==BACKLIGHT_OFF;}
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
    choice=direction<0?(choice?choice-1u:BACKLIGHT_OFF):(choice==BACKLIGHT_OFF?0u:choice+1u);
    mark_record_dirty();++revision;return true;
}
/* Wait for the saved choice before allowing feedback, including saved Off. */
const char *ln_display_click_label(void){return click_labels[click_tone];}
uint8_t ln_display_click_tone(void){return loaded||click_fallback_ready||click_changed?click_tone:1u;}
bool ln_display_click_adjust(int32_t direction){
    if(!direction)return false;
    click_tone=(uint8_t)((click_tone+(direction<0?3u:1u))&3u);
    click_changed=true;
    mark_record_dirty();++revision;return true;
}
uint32_t ln_auto_shutdown_seconds(bool headphones){return shutdown_seconds[shutdown_choice[headphones?1:0]];}
bool ln_auto_shutdown_adjust(bool headphones,int32_t direction){
    if(!direction)return false;
    uint8_t *value=&shutdown_choice[headphones?1:0];
    *value=direction<0?(*value?*value-1u:8u):(*value==8u?0u:*value+1u);
    mark_record_dirty();++revision;return true;
}
static const char *auto_shutdown_label(uint32_t item){
    char *out=shutdown_label[item];uint32_t at=0;
    const char *p=item?"Headphones in: ":"Headphones out: ";
    while(*p)out[at++]=*p++;
    p=shutdown_labels[shutdown_choice[item]];while(*p)out[at++]=*p++;
    out[at]=0;return out;
}
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
    mark_record_dirty();++revision;return true;
}
/* SETT stores display, photo, video, battery and music state in one current
 * envelope. Its 36-byte overhead leaves 444 bytes for the music payload. */
static bool valid_photo(const uint8_t *resume){
    uint32_t flags=ln_read_le32(resume+8);
    return ln_read_le32(resume+4)<=65535u&&(flags&255u)<=5u&&((flags>>8)&255u)<=3u&&(flags>>16)<=2u;
}
static int malformed_record(void){click_fallback_ready=true;return -1;}
static int read_record(uint8_t raw[480],uint32_t *offset,uint32_t *length){
    uint32_t bytes=480;
    if(ln_storage_busy()||!ln_storage_mounted()||!ln_storage_settings(false,raw,&bytes))return 0;
    if(bytes>480)return malformed_record();
    if(!bytes){*offset=*length=0;loaded=true;return 1;}
    uint32_t out_offset=0,out_length=0,saved_choice=choice,saved_capacity=1200;bool saved_clock_12=false;uint8_t saved_video_options=8u;
    uint8_t saved_photo[16]={0};uint32_t saved_video[2]={0};
    if(bytes<36||ln_read_le32(raw)!=0x54544553u||ln_read_le32(raw+bytes-4)!=ln_crc32(raw,bytes-4))return malformed_record();
    uint32_t n=(uint32_t)raw[4]|((uint32_t)raw[5]<<8),f=raw[14];
    if(n!=bytes-36||((raw[7]>>1)&3u)>2u||raw[6]>BACKLIGHT_OFF||(raw[15]&15u)>8u||(raw[15]>>4)>8u||(f&7u)>5||((f>>5)&3u)>2||(f&128u))return malformed_record();
    saved_choice=raw[6];saved_clock_12=(raw[7]&1u)!=0;
    saved_video_options=(uint8_t)(((raw[7]>>1)&3u)|(((raw[7]>>3)&1u)<<2)|(((raw[7]>>4)&1u?0u:1u)<<3)|(((raw[7]>>5)&1u)<<4));
    ln_write_le32(saved_photo,ln_read_le32(raw+8));ln_write_le32(saved_photo+4,(uint32_t)raw[12]|((uint32_t)raw[13]<<8));
    ln_write_le32(saved_photo+8,(f&7u)|(((f>>3)&3u)<<8)|(((f>>5)&3u)<<16));ln_write_le32(saved_photo+12,ln_read_le32(raw+16));
    saved_video[0]=ln_read_le32(raw+20);saved_video[1]=ln_read_le32(raw+24);
    if(!valid_photo(saved_photo))return malformed_record();
    saved_capacity=ln_read_le32(raw+28);
    if(saved_capacity<50u||saved_capacity>10000u||saved_capacity%50u)return malformed_record();
    out_offset=32;out_length=bytes-36;
    /* Commit only after the complete envelope has passed validation. */
    if(!loaded){
        if(!dirty&&(choice!=saved_choice||battery_capacity!=saved_capacity||clock_12!=saved_clock_12||shutdown_choice[0]!=(raw[15]&15u)||shutdown_choice[1]!=(raw[15]>>4))){
            shutdown_choice[0]=raw[15]&15u;shutdown_choice[1]=raw[15]>>4;choice=saved_choice;battery_capacity=saved_capacity;clock_12=saved_clock_12;++revision;
        }
        if(!click_changed&&click_tone!=(raw[7]>>6)){click_tone=raw[7]>>6;++revision;}
        for(uint32_t i=0;i<16;++i)photo_resume[i]=saved_photo[i];
        video_resume[0]=saved_video[0];video_resume[1]=saved_video[1];video_options=saved_video_options;
    }
    *offset=out_offset;*length=out_length;loaded=true;return 1;
}
static int write_record(uint8_t raw[480],const uint8_t *data,uint32_t length,bool existing){
    if(length>444||!valid_photo(photo_resume)||battery_capacity<50u||battery_capacity>10000u||battery_capacity%50u)return 0;
    uint32_t index=ln_read_le32(photo_resume+4),flags=ln_read_le32(photo_resume+8);
    if(index>65535u||(flags&255u)>5u||((flags>>8)&255u)>3u||(flags>>16)>2u)return 0;
    uint8_t packed7=(uint8_t)((clock_12?1u:0u)|((video_options&3u)<<1)|(((video_options>>2)&1u)<<3)|(((video_options&8u)?0u:1u)<<4)|(((video_options>>4)&1u)<<5)|(click_tone<<6));
    uint8_t packed14=(uint8_t)((flags&7u)|(((flags>>8)&3u)<<3)|(((flags>>16)&3u)<<5));
    uint8_t packed15=(uint8_t)(shutdown_choice[0]|(shutdown_choice[1]<<4));
    uint32_t snapshot_revision=record_revision;
    bool unchanged=existing&&raw[4]==(uint8_t)length&&raw[5]==(uint8_t)(length>>8)&&raw[6]==choice&&
        raw[7]==packed7&&ln_read_le32(raw+8)==ln_read_le32(photo_resume)&&
        raw[12]==(uint8_t)index&&raw[13]==(uint8_t)(index>>8)&&raw[14]==packed14&&raw[15]==packed15&&
        ln_read_le32(raw+16)==ln_read_le32(photo_resume+12)&&ln_read_le32(raw+20)==video_resume[0]&&
        ln_read_le32(raw+24)==video_resume[1]&&ln_read_le32(raw+28)==battery_capacity;
    if(unchanged)for(uint32_t i=0;i<length;++i)if(raw[32+i]!=data[i]){unchanged=false;break;}
    if(unchanged){if(record_revision==snapshot_revision)dirty=false;return 1;}
    for(uint32_t i=length;i;--i)raw[32+i-1]=data[i-1];
    ln_write_le32(raw,0x54544553u);raw[4]=(uint8_t)length;raw[5]=(uint8_t)(length>>8);raw[6]=(uint8_t)choice;
    raw[7]=packed7;
    ln_write_le32(raw+8,ln_read_le32(photo_resume));raw[12]=(uint8_t)index;raw[13]=(uint8_t)(index>>8);
    raw[14]=packed14;raw[15]=packed15;
    ln_write_le32(raw+16,ln_read_le32(photo_resume+12));ln_write_le32(raw+20,video_resume[0]);ln_write_le32(raw+24,video_resume[1]);
    ln_write_le32(raw+28,battery_capacity);ln_write_le32(raw+32+length,ln_crc32(raw,32+length));
    uint32_t bytes=length+36;
    if(!ln_storage_settings(true,raw,&bytes))return 0;
#if !defined(LINNET_PROFILE_RELEASE)
    if(record_publishes!=UINT32_MAX)++record_publishes;
#endif
    if(record_revision==snapshot_revision)dirty=false;return 1;
}
bool ln_display_settings_photo_get(uint8_t out[16]){
    if(!loaded||!out)return false;
    for(uint32_t i=0;i<16;++i)out[i]=photo_resume[i];return true;
}
void ln_display_settings_photo_set(const uint8_t in[16]){
    if(!loaded||!in)return;bool changed=false;
    for(uint32_t i=0;i<16;++i)if(photo_resume[i]!=in[i])changed=true;
    if(!changed)return;
    for(uint32_t i=0;i<16;++i)photo_resume[i]=in[i];mark_record_dirty();
}
bool ln_display_settings_video_get(uint32_t out[2]){
    if(!loaded||!out)return false;out[0]=video_resume[0];out[1]=video_resume[1];return true;
}
void ln_display_settings_video_set(const uint32_t in[2]){
    if(!loaded||!in||(in[0]==video_resume[0]&&in[1]==video_resume[1]))return;
    video_resume[0]=in[0];video_resume[1]=in[1];mark_record_dirty();
}
void ln_display_game_best_set(uint32_t index,uint16_t score){
    if(index>=LN_GAME_COUNT||score<=game_best[index])return;
    game_best[index]=score;theme_dirty=true;++theme_revision;++revision;
}
bool ln_display_settings_video_options_get(uint8_t *out){if(!loaded||!out)return false;*out=video_options;return true;}
void ln_display_settings_video_options_set(uint8_t options){
    options&=31u;if(!loaded||options==video_options)return;
    video_options=options;mark_record_dirty();++revision;
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
    if(write)return write_record(raw,data,*length,offset==32u);
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
    uint8_t payload[128];uint32_t length=sizeof(payload);
    if(!theme_loaded){
        int result=ln_storage_theme(false,payload,&length);
        if(!result)return;
        theme_loaded=true;theme_available=result==1;
        uint32_t saved=UINT32_MAX;
        if(theme_available&&length){
            uint32_t version=length>=8u?ln_read_le32(payload+4):UINT32_MAX;
            uint32_t suffix=version==0u?1u:version==1u?5u:version==2u?7u:version==3u?25u:0u;
            uint32_t id_length=length>=8u+suffix?length-8u-suffix:0u;
            if(length<9u||length>sizeof payload||(version==0u&&length>89u)||!suffix||length<8u+suffix||
               ln_read_le32(payload)!=0x534d4854u||payload[8u+id_length]||
               !theme_id_valid(payload+8,id_length))theme_available=false;
            if(theme_available&&length>8u+suffix){
                for(uint32_t i=0;i<ln_ui_theme_count;++i){
                    const char *id=ln_ui_themes[i].id;uint32_t at=0;
                    while(at<id_length&&id[at]&&(uint8_t)id[at]==payload[8+at])++at;
                    if(at==id_length&&!id[at]){saved=i;break;}
                }
            }
            if(theme_available&&(version==1u||version==2u||version==3u)){
                uint32_t stored=version==1u?2u:version==2u?3u:LN_GAME_COUNT;
                uint32_t scores=length-stored*2u;
                for(uint32_t i=0;i<stored;++i){game_best[i]=ln_read_le16(payload+scores+i*2u);ln_games_best_set(i,game_best[i]);}
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
    ln_write_le32(payload,0x534d4854u);
#if LINNET_HAS_GAMES
    ln_write_le32(payload+4,3u);
#else
    ln_write_le32(payload+4,0u);
#endif
    for(uint32_t i=0;i<count;++i)payload[8+i]=(uint8_t)id[i];payload[8+count]=0;
#if LINNET_HAS_GAMES
    for(uint32_t i=0;i<LN_GAME_COUNT;++i)ln_write_le16(payload+9u+count+i*2u,game_best[i]);
    length=9u+count+LN_GAME_COUNT*2u;
#else
    length=9u+count;
#endif
    uint32_t snapshot_revision=theme_revision;
    int result=ln_storage_theme(true,payload,&length);
#if !defined(LINNET_PROFILE_RELEASE)
    if(result==1&&theme_publishes!=UINT32_MAX)++theme_publishes;
#endif
    if(result<0){theme_available=false;theme_dirty=false;++revision;}
    else if(result==1&&snapshot_revision==theme_revision){theme_dirty=false;++revision;}
}
static void menus_step(void){
    if(menus_loaded||!ln_storage_mounted())return;
    const uint32_t generation=0x4d454e55u;int result;uint32_t transferred=0;
    if(menus_phase==0){result=ln_storage_media_open("/.LINNET/MENUS.BIN",generation);if(!result)return;if(result<0){menus_loaded=true;return;}menus_phase=1;return;}
    if(menus_phase==1){result=ln_storage_media_poll_deferred(generation,&menus_file,0);if(!result)return;if(result<0||menus_file.size!=sizeof menus_data){menus_loaded=true;return;}menus_phase=2;}
    if(menus_phase==2){result=ln_storage_media_read(&menus_file,0,menus_data,sizeof menus_data,generation);if(!result)return;if(result<0){menus_loaded=true;return;}menus_phase=3;return;}
    result=ln_storage_media_poll_deferred(generation,0,&transferred);if(!result)return;
    if(result>0&&transferred==sizeof menus_data)(void)ln_ui_menu_load(menus_data,sizeof menus_data);
    menus_loaded=true;++revision;
}
static void games_step(void){
    if(games_loaded||!menus_loaded||!ln_storage_mounted())return;
    const uint32_t generation=0x47414d45u;int result;uint32_t transferred=0;
    if(games_phase==0){result=ln_storage_media_open("/.LINNET/GAMES.BIN",generation);if(!result)return;if(result<0){games_loaded=true;return;}games_phase=1;return;}
    if(games_phase==1){result=ln_storage_media_poll_deferred(generation,&games_file,0);if(!result)return;if(result<0||games_file.size!=sizeof games_data){games_loaded=true;return;}games_phase=2;}
    if(games_phase==2){result=ln_storage_media_read(&games_file,0,games_data,sizeof games_data,generation);if(!result)return;if(result<0){games_loaded=true;return;}games_phase=3;return;}
    result=ln_storage_media_poll_deferred(generation,0,&transferred);if(!result)return;
    if(result>0&&transferred==sizeof games_data&&ln_read_le32(games_data)==0x454d4147u&&
       (games_data[4]==1u||games_data[4]==2u||games_data[4]==3u)&&
       !(games_data[5]&~(games_data[4]==1u?7u:255u))&&
       (games_data[4]==3u?!(games_data[6]&~(LN_GAME_MASK>>8)):!games_data[6])&&!games_data[7]&&
       ln_read_le32(games_data+8)==ln_crc32(games_data,8u))
        {uint16_t mask=games_data[5];if(games_data[4]==3u)mask|=(uint16_t)games_data[6]<<8;
         else if((games_data[4]==1u&&mask==7u)||(games_data[4]==2u&&mask==15u))mask=LN_GAME_MASK;
         ln_games_configure(mask);}
    games_loaded=true;++revision;
}
static void about_step(void){
    if(about_loaded||!games_loaded||!ln_storage_mounted())return;
    const uint32_t generation=0x41424f54u;int result;uint32_t transferred=0;
    if(about_phase==0){result=ln_storage_media_open("/.LINNET/ABOUT.BIN",generation);if(!result)return;if(result<0){about_loaded=true;return;}about_phase=1;return;}
    if(about_phase==1){result=ln_storage_media_poll_deferred(generation,&about_file,0);if(!result)return;if(result<0||about_file.size!=sizeof about_data){about_loaded=true;return;}about_phase=2;}
    if(about_phase==2){result=ln_storage_media_read(&about_file,0,about_data,sizeof about_data,generation);if(!result)return;if(result<0){about_loaded=true;return;}about_phase=3;return;}
    result=ln_storage_media_poll_deferred(generation,0,&transferred);if(!result)return;
    if(result>0&&transferred==sizeof about_data&&
       about_data[0]=='A'&&about_data[1]=='B'&&about_data[2]=='T'&&about_data[3]=='1'&&
       about_data[4]==1u&&about_data[5]<=26u&&about_data[6]<=100u&&about_data[7]==0u&&
       ln_read_le32(about_data+1020)==ln_crc32(about_data,1020u)){
        bool valid=true;
        for(uint32_t i=0;i<about_data[5]&&valid;++i){
            const uint8_t *row=about_data+16u+i*36u;bool ended=false;
            for(uint32_t j=0;j<36u;++j){
                if(!row[j])ended=true;
                else if(ended||row[j]<32u||row[j]>126u)valid=false;
            }
            if(!ended)valid=false;
        }
        if(valid){about_count=about_data[5];about_percent=about_data[6];}
    }
    about_loaded=true;++revision;
}
static void about_ata_text(const char *prefix,const char *value){
    if(about_ata_count>=8u||!value||!value[0])return;
    char *out=about_ata_rows[about_ata_count++];uint32_t at=0;
    while(*prefix&&at<63u)out[at++]=*prefix++;
    while(*value&&at<63u)out[at++]=*value++;
    out[at]=0;
}
static void about_ata_number(const char *prefix,uint32_t value){
    char digits[10];uint32_t count=0;
    do{digits[count++]=(char)('0'+value%10u);value/=10u;}while(value&&count<10u);
    char text[12];for(uint32_t i=0;i<count;++i)text[i]=digits[count-i-1u];text[count]=0;
    about_ata_text(prefix,text);
}
static void about_ata_step(void){
    if(about_ata_ready)return;
    struct ln_ata_info info;ln_ata_snapshot(&info);
    if(!info.initialized)return;
    about_ata_text("Drive model  ",info.model);
    about_ata_text("Drive serial  ",info.serial);
    about_ata_text("Drive FW  ",info.firmware);
    about_ata_text("Drive type  ",info.media_kind==LN_ATA_MEDIA_ROTATING?"Hard disk":
                   info.media_kind==LN_ATA_MEDIA_SOLID_STATE?"Solid state":"Unknown");
    if(info.rotation_rpm)about_ata_number("Rotation  ",info.rotation_rpm);
    if(info.physical_sector_bytes)about_ata_number("Physical sector  ",info.physical_sector_bytes);
    about_ata_text("Addressing  ",info.lba48?"LBA48":"LBA28");
    about_ata_text("Write cache  ",info.write_cache_enabled?"On":"Off");
    about_ata_ready=true;++revision;
}
uint32_t ln_display_about_count(void){return 2u+(about_count?about_count:1u)+about_ata_count;}
uint32_t ln_display_about_percent(void){return about_percent;}
const char *ln_display_about_row(uint32_t item){
    if(item==0u)return about_version;
    if(item==1u)return about_build;
    item-=2u;
    if(item<about_count)return (const char *)(about_data+16u+item*36u);
    if(!about_count){if(!item)return "Sync in Media Manager for details";--item;}
    else item-=about_count;
    return item<about_ata_count?about_ata_rows[item]:"";
}
static void settings_work(bool may_write,bool presented,uint32_t presented_revision,bool flush){
    if(!may_write||((loaded&&!dirty)&&(theme_loaded&&!theme_dirty))||ln_storage_busy()||!ln_storage_mounted())return;
    if(!flush&&loaded&&dirty&&theme_loaded&&!theme_dirty&&!record_publish_due())return;
    /* Once loading is complete, a theme waiting for its first frame must not
     * start disk write preparation. Independent settings work may still proceed. */
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
    if(!flush&&dirty&&!record_publish_due())return;
    uint8_t raw[480];uint32_t offset,bytes;
    if(read_record(raw,&offset,&bytes)!=1||!dirty||!may_write)return;
    /* Preparation can yield to other owners; re-read before publication. */
    if(read_record(raw,&offset,&bytes)!=1)return;
    (void)write_record(raw,raw+offset,bytes,offset==32u);
}
static void settings_step(bool may_write,bool presented,uint32_t presented_revision,bool flush){
    if(step_busy)return;
    step_busy=true;if(may_write){menus_step();games_step();about_step();}about_ata_step();settings_work(may_write,presented,presented_revision,flush);step_busy=false;
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
    if(n->kind==LN_UI_VIRTUAL_LIST&&item<2u&&text_equal(n->text,"Automatic shutdown"))return auto_shutdown_label(item);
    if(n->kind==LN_UI_VIRTUAL_LIST&&item==0&&n->text){
        const char *a=n->text,*b="Display timeout";while(*a&&*a==*b){++a;++b;}
        if(!*a&&!*b)return ln_display_settings_label();
        a=n->text;b="Battery capacity";while(*a&&*a==*b){++a;++b;}
        if(!*a&&!*b)return ln_battery_capacity_label();
    }
    return fallback;
}
