#ifndef LINNET_MUSIC_MENU_H
#define LINNET_MUSIC_MENU_H
#include "ui/runtime/ui.h"

/* Presentation IDs do not change MENUS.BIN or the underlying service actions. */
enum { LN_MUSIC_COVER_FLOW=16, LN_MUSIC_MORE=17 };
static inline bool ln_music_menu_more(uint32_t id){
    return id==5u||id==6u||id==10u||id==11u||id==12u||id==13u||id==14u;
}
static inline bool ln_music_menu_scene_enabled(const char *id){
    for(uint32_t i=0;i<ln_ui_scene_count;++i){const char *a=id,*b=ln_ui_scenes[i].id;
        while(*a&&*a==*b){++a;++b;}
        if(!*a&&!*b)return (ln_ui_enabled_scenes&(UINT64_C(1)<<i))!=0;
    }
    return false;
}
static inline uint32_t ln_music_menu_category(bool more,uint32_t row){
    bool covers=!more&&ln_music_menu_scene_enabled("linnet.system.cover-flow"),has_more=false;
    for(uint32_t i=0;i<ln_ui_menu_count(LN_MENU_MUSIC);++i){
        uint32_t id=ln_ui_menu_item(LN_MENU_MUSIC,i);bool secondary=ln_music_menu_more(id);
        if(secondary)has_more=true;
        if(secondary!=more)continue;
        /* Cover Flow follows the conventional browsing categories, before Search. */
        if(id==8u&&covers){if(!row)return LN_MUSIC_COVER_FLOW;--row;covers=false;}
        if(!row)return id;--row;
    }
    if(covers){if(!row)return LN_MUSIC_COVER_FLOW;--row;}
    return !more&&has_more&&!row?LN_MUSIC_MORE:UINT32_MAX;
}
static inline uint32_t ln_music_menu_count(bool more){
    uint32_t count=0;while(ln_music_menu_category(more,count)!=UINT32_MAX)++count;return count;
}
enum { LN_SOUND_ROOT, LN_SOUND_EQ, LN_SOUND_ADVANCED };
enum { LN_SOUND_CLICKER=13, LN_SOUND_CUSTOM_EQ, LN_SOUND_MORE };
static inline uint32_t ln_sound_menu_action(uint32_t view,uint32_t row,bool extended,bool clicker){
    static const uint8_t root[]={0,1,6,LN_SOUND_CLICKER,LN_SOUND_CUSTOM_EQ,LN_SOUND_MORE};
    static const uint8_t advanced[]={3,4,2,5,7};
    if(view==LN_SOUND_ROOT){if(!clicker&&row>=3u)++row;return row<sizeof(root)?root[row]:UINT32_MAX;}
    if(view==LN_SOUND_ADVANCED)return row<(extended?5u:4u)?advanced[row]:UINT32_MAX;
    if(view==LN_SOUND_EQ)return row<(extended?5u:2u)?row+(extended?8u:7u):UINT32_MAX;
    return UINT32_MAX;
}
static inline uint32_t ln_sound_menu_count(uint32_t view,bool extended,bool clicker){
    return view==LN_SOUND_ROOT?(clicker?6u:5u):view==LN_SOUND_EQ?(extended?5u:2u):(extended?5u:4u);
}
#endif
