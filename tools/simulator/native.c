/* Desktop oracle executes the same generated scenes and native renderer. */
#include "ui/runtime/ui.h"
#include "services/display/clock.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
static uint32_t sample_battery=80u,sample_clock=9u*3600u+41u*60u,sample_playback,sample_modes;
static bool sample_art;
uint32_t ln_ui_battery_status(void){return sample_battery;}
uint32_t ln_ui_clock_seconds(void){return sample_clock;}
uint32_t ln_ui_playback_status(void){return sample_playback;}
uint32_t ln_ui_playback_modes(void){return sample_modes;}
const struct ln_ui_asset *ln_ui_now_playing_art(uint32_t *revision){
    *revision=sample_art?1u:0u;return sample_art&&ln_ui_asset_count?&ln_ui_assets[0]:0;
}
/* Explicit sample metadata; device builds bind these keys to the music service. */
static bool music_category_node(const struct ln_ui_node *node){
    for(uint32_t i=0;i<ln_ui_scene_count;++i){
        const struct ln_ui_scene *scene=&ln_ui_scenes[i];
        if(strcmp(scene->id,"linnet.system.music"))continue;
        for(uint32_t j=0;j<scene->count;++j)if(&scene->nodes[j]==node)return true;
        break;
    }
    return false;
}
uint32_t ln_ui_dynamic_count(const struct ln_ui_node *node,uint32_t fallback){
    if(music_category_node(node)&&(node->kind==LN_UI_VIRTUAL_LIST||node->kind==LN_UI_SCROLLBAR))return 4u;
    return fallback;
}
const char *ln_ui_dynamic_text(const struct ln_ui_node*n,uint32_t item,const char*fallback){
    if(!n->text)return fallback;
    if(item==UINT32_MAX&&strcmp(n->text,"Right: Actions  Menu: Back")==0&&music_category_node(n))
        return "Select: Choose  Menu: Back";
    if(item!=UINT32_MAX&&strcmp(n->text,"Track ")==0&&music_category_node(n)){
        static const char *const categories[]={"All Tracks","Artists","Albums","Playlists"};
        if(item<4u)return categories[item];
    }
    if(item!=UINT32_MAX&&strcmp(n->text,"Option ")==0){
        static const char *const labels[]={"Shuffle: Off","Repeat: Off","Play queue","Sound settings","Sleep timer","Favorite: No","Save bookmark","No bookmark saved","Restart track","Back 10 seconds","Forward 10 seconds","Save queue as playlist...","Stop"};
        if(item==0)return sample_modes&1u?"Shuffle: Songs":"Shuffle: Off";
        if(item==1)return (sample_modes>>1)==2u?"Repeat: One":(sample_modes>>1)==1u?"Repeat: All":"Repeat: Off";
        return item<13u?labels[item]:fallback;
    }
    if(item!=UINT32_MAX)return fallback;
    if(!strcmp(n->text,"Native playback shell"))return sample_playback?"":"Stopped";
    if(!strcmp(n->text,"Track position"))return "1 of 12";
    if(!strcmp(n->text,"Track album"))return "Sample album";
    if(!strcmp(n->text,"Track elapsed"))return "1:24";
    if(!strcmp(n->text,"Track remaining"))return "-2:36";
    return fallback;
}
static struct ln_calendar sample_calendar={2026,9,7,9,41,0,1};
static uint32_t sample_read=LN_CALENDAR_READ_VALID,sample_result=LN_CALENDAR_SAVED,sample_busy,save_calls;
static bool save_presented;
bool ln_ui_clock_begin(void){
    ln_clock_editor_cancel();save_presented=false;
    sample_calendar.hour=(uint8_t)(sample_clock<86400u?sample_clock/3600u:0);
    sample_calendar.minute=(uint8_t)(sample_clock<86400u?(sample_clock/60u)%60u:0);
    ln_clock_editor_begin(&sample_calendar,sample_read==LN_CALENDAR_READ_VALID);
    if(sample_read==LN_CALENDAR_READ_UNAVAILABLE)ln_clock_editor_block("Clock unavailable. Edit, retry Save.");
    return true;
}
bool ln_ui_clock_input(struct ln_ui_state*s,uint32_t kind,int32_t value){return ln_clock_editor_input(s,kind,value);}
void ln_ui_clock_cancel(void){ln_clock_editor_cancel();}
const char *ln_ui_clock_text(const struct ln_ui_node*n,uint32_t item,const char*fallback){return ln_clock_editor_text(n,item,fallback);}
static void clock_step(struct ln_ui_state*s){
    if(!save_presented)return;save_presented=false;
    struct ln_calendar requested;if(!ln_clock_editor_request(&requested))return;
    if(s->hold)ln_clock_editor_block("Unlock Hold before saving.");
    else{
        ++save_calls;ln_clock_editor_result((enum ln_calendar_result)sample_result);
        if(sample_result==LN_CALENDAR_SAVED){sample_calendar=requested;sample_clock=(uint32_t)requested.hour*3600u+(uint32_t)requested.minute*60u;
            (void)ln_ui_show(s,"linnet.system.clock");}
    }
    ln_ui_refresh(s);
}
static uint16_t pixels[LINNET_UI_WIDTH*LINNET_UI_HEIGHT];
static uint32_t damage_count;
static void damage(int32_t x,int32_t y,int32_t w,int32_t h){(void)x;(void)y;(void)w;(void)h;++damage_count;}
static uint32_t crc(void){
    uint32_t c=0xffffffffu;
    for(uint32_t i=0;i<LINNET_UI_WIDTH*LINNET_UI_HEIGHT;++i)for(unsigned j=0;j<2;++j){
        c^=(pixels[i]>>(j*8))&255u;for(unsigned b=0;b<8;++b)c=(c>>1)^((0u-(c&1u))&0xedb88320u);
    }
    return c^0xffffffffu;
}
static int snapshot(const struct ln_ui_state *state,const char *directory,uint32_t index){
    char name[4096];if(snprintf(name,sizeof name,"%s/frame-%05u.rgb565",directory,index)>=(int)sizeof name)return 0;
    FILE *file=fopen(name,"wb");if(!file)return 0;
    for(uint32_t i=0;i<LINNET_UI_WIDTH*LINNET_UI_HEIGHT;++i){unsigned char p[2]={(unsigned char)pixels[i],(unsigned char)(pixels[i]>>8)};if(fwrite(p,1,2,file)!=2){fclose(file);return 0;}}
    if(fclose(file))return 0;
    printf("{\"frame\":%u,\"theme\":%u,\"battery\":%u,\"clock\":%u,\"playback\":%u,\"scene\":%u,\"selected\":%u,\"crc32\":%u,\"paint_count\":%u,\"painted_pixels\":%u,\"visible_items\":%u,\"scene_epoch\":%u,\"transitions\":%u,\"damage_count\":%u,\"action\":%u,\"clock_save_calls\":%u}\n",
        index,ln_ui_theme_index(),sample_battery,sample_clock,sample_playback,state->scene,state->selected,crc(),state->paint_count,state->painted_pixels,state->visible_items,state->scene_epoch,state->transitions,damage_count,state->action,save_calls);
    return 1;
}
int main(int argc,char **argv){
    if(argc!=2&&(argc!=3||strcmp(argv[2],"--all-scenes")))return 2;
    struct ln_ui_state state;ln_ui_init(&state);ln_ui_render(&state,pixels,damage);
    if(!snapshot(&state,argv[1],0))return 3;
    uint32_t kind,repeat,capture,index=0,total=0,simulated_us=0;int32_t value;
    while(scanf("%u %d %u %u",&kind,&value,&repeat,&capture)==4){
        if(kind>12u||!repeat||repeat>100000u||total>100000u-repeat||capture>1u)return 4;
        for(uint32_t i=0;i<repeat;++i){if(kind<=4u&&kind)ln_ui_input(&state,kind,value);
            else if(kind==0u&&value==1)ln_ui_refresh(&state);
            else if(kind==5u){if(value!=-1&&((value&255)>100||value<0||value>1023))return 4;sample_battery=(uint32_t)value;}
            else if(kind==6u){if(value< -1||value>=86400)return 4;sample_clock=(uint32_t)value;}
            else if(kind==7u){if(value<0||value>2)return 4;sample_playback=(uint32_t)value;}
            else if(kind==8u){if(value<0||value>4)return 4;sample_result=(uint32_t)value;}
            else if(kind==9u){if(value<0||value>2)return 4;sample_read=(uint32_t)value;}
            else if(kind==10u){if(value<0||value>2)return 4;sample_busy=(uint32_t)value;}
            else if(kind==11u){if(value<0||value>5)return 4;sample_modes=(uint32_t)value;}
            else if(kind==12u){if(value<0||value>1)return 4;if(sample_art!=(value!=0)){sample_art=value!=0;ln_ui_refresh(&state);}}
            if(state.action==LINNET_UI_ACTION_SHUFFLE||state.action==LINNET_UI_ACTION_REPEAT){
                uint32_t action=ln_ui_take_action(&state);
                sample_modes=action==LINNET_UI_ACTION_SHUFFLE?sample_modes^1u:(sample_modes&1u)|((((sample_modes>>1)+1u)%3u)<<1);
                ln_ui_refresh(&state);
            }
            simulated_us+=33333u;if(ln_games_tick(simulated_us))ln_ui_refresh(&state);
            clock_step(&state);ln_ui_render(&state,pixels,damage);save_presented=ln_clock_editor_pending();}
        total+=repeat;
        if(capture){if(++index>512u||!snapshot(&state,argv[1],index))return 5;}
    }
    if(!feof(stdin))return 6;
    if(argc==3){
        for(uint32_t scene=1;scene<ln_ui_scene_count&&scene<32u;++scene){
            if(!(ln_ui_enabled_scenes&(1u<<scene)))continue;
            (void)ln_ui_show(&state,ln_ui_scenes[scene].id);
            ln_ui_refresh(&state);ln_ui_render(&state,pixels,damage);
            if(++index>512u||!snapshot(&state,argv[1],index))return 7;
        }
        return 0;
    }
    if(++index>513u||!snapshot(&state,argv[1],index))return 7;
    return 0;
}
