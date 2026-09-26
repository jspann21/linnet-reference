#include "targets/video5g-m25/games.h"
#if defined(LINNET_AUDIO)
#include "hal/api/audio.h"
#include "services/music/player.h"
#endif
#if defined(LINNET_STORAGE)
#include "services/display/settings.h"
#endif

enum { COMET, PULSE };
enum { PLAY=1u, PAUSED, LOST, WATCH, MISTAKE, WON };
static uint8_t installed=3u,game,games_phase,paused_phase,hearts,focus,sequence[24],entered,level,flash;
static uint16_t ship=160,energy,score,best[2];
static uint32_t random_state=0x9e3779b9u,last_tick,spawn_at,flash_until,invulnerable_until,hud_revision,energy_carry;
static uint32_t buttons;
static uint8_t sound_pending;
static struct {int16_t x,y;uint8_t size,live;uint32_t fraction;} rock[12];
static char score_text[48];
static const char *const names[]={"Comet Run","Pulse Path"};

static uint32_t random_next(void){random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;return random_state;}
static void number(char **out,uint32_t value){char reverse[10];uint32_t n=0;do{reverse[n++]=(char)('0'+value%10u);value/=10u;}while(value);while(n)*(*out)++=reverse[--n];}
static void append(char **out,const char *text){while(*text)*(*out)++=*text++;}
uint32_t ln_games_count(void){return (installed&1u?1u:0u)+(installed&2u?1u:0u);}
const char *ln_games_label(uint32_t row){for(uint32_t i=0;i<2u;++i)if(installed&(1u<<i)){if(!row)return names[i];--row;}return 0;}
const char *ln_games_description(uint32_t row){
    for(uint32_t i=0;i<2u;++i)if(installed&(1u<<i)){
        if(!row)return i==COMET?"Thread through the meteor field.":
            "Remember the lights. Find the path.";
        --row;
    }
    return "Choose games in Linnet Media.";
}
void ln_games_configure(uint8_t mask){installed=mask&3u;}
void ln_games_best_set(uint32_t index,uint16_t value){if(index<2u)best[index]=value;}
bool ln_games_playing(void){return games_phase==PLAY||games_phase==WATCH||games_phase==MISTAKE;}
uint32_t ln_games_hud_revision(void){return hud_revision;}
uint32_t ln_games_deadline(uint32_t now){
    if(!ln_games_playing())return UINT32_MAX;
    if(!last_tick)return now;
    if(game==COMET)return (int32_t)(last_tick+33333u-now)>0?last_tick+33333u:now;
    if(games_phase==WATCH||games_phase==MISTAKE||flash)
        return (int32_t)(flash_until-now)>0?flash_until:now;
    return UINT32_MAX;
}
static void finish(bool won);
static void new_pulse(void){
    if(level>=24u){finish(true);return;}
    sequence[level]=(uint8_t)(random_next()&3u);++level;entered=0;
    flash=sequence[0]+1u;flash_until=last_tick+500000u;games_phase=WATCH;sound_pending=(uint8_t)(5u+sequence[0]);
}
void ln_games_start(uint32_t row){
    for(uint32_t i=0;i<2u;++i)if(installed&(1u<<i)){if(!row){game=(uint8_t)i;break;}--row;}
    random_state^=last_tick+0x6d2b79f5u;games_phase=paused_phase=PLAY;score=0;hearts=3u;focus=0u;sound_pending=1u;
    if(game==COMET){ship=160u;energy=100u;energy_carry=0;spawn_at=last_tick+600000u;invulnerable_until=last_tick+1200000u;for(uint32_t i=0;i<12u;++i)rock[i].live=0;}
    else{level=0u;new_pulse();}
    last_tick=0;++hud_revision;
}
static void finish(bool won){games_phase=won?WON:LOST;sound_pending=4u;if(score>best[game]){
        best[game]=score;
#if defined(LINNET_STORAGE)
        ln_display_game_best_set(game,score);
#endif
    }}
int ln_games_input(uint32_t kind,int32_t value){
    if(kind==1u){if(!value)return 1;if(games_phase==PLAY&&game==COMET){
            int32_t steps=value<-24?-24:value>24?24:value;
            int32_t next=(int32_t)ship+steps*12;if(next<18)next=18;if(next>302)next=302;ship=(uint16_t)next;}
        else if(games_phase==PLAY&&game==PULSE)focus=(uint8_t)((focus+value%4+4)&3u);return 1;}
    if(kind!=2u)return 0;
    uint32_t pressed=(uint32_t)value&~buttons;buttons=(uint32_t)value;
    if(pressed&1u){if(games_phase==PAUSED||games_phase==LOST||games_phase==WON)return 2;
        paused_phase=games_phase;games_phase=PAUSED;return 1;}
    if(pressed&2u){if(games_phase==PLAY||games_phase==WATCH||games_phase==MISTAKE){paused_phase=games_phase;games_phase=PAUSED;}
        else if(games_phase==PAUSED){games_phase=paused_phase;if(game==PULSE)last_tick=0;}return 1;}
    if((games_phase==LOST||games_phase==WON)&&(pressed&16u)){
        ln_games_start(game==PULSE&&(installed&1u)?1u:0u);return 1;}
    if(games_phase!=PLAY)return 1;
    if(game==COMET){
        if(pressed&4u)ship=ship<286u?ship+16u:302u;
        if(pressed&8u)ship=ship>34u?ship-16u:18u;
        if((pressed&16u)&&energy>=40u){energy-=40u;invulnerable_until=last_tick+800000u;sound_pending=2u;}
    }else{
        if(pressed&4u)focus=(focus+1u)&3u;
        if(pressed&8u)focus=(focus+3u)&3u;
        if(pressed&16u){
            flash=focus+1u;flash_until=last_tick+230000u;
            if(focus!=sequence[entered]){
                sound_pending=3u;if(hearts)--hearts;
                if(!hearts)finish(false);
                else{entered=0;games_phase=MISTAKE;flash_until=last_tick+450000u;}
            }else {sound_pending=(uint8_t)(5u+focus);if(++entered==level){score+=level*10u;new_pulse();}}
        }
    }
    return 1;
}
bool ln_games_tick(uint32_t now){
    uint16_t old_score=score;uint8_t old_hearts=hearts,old_phase=games_phase;
    if(!last_tick){last_tick=now;
        if(game==COMET){spawn_at=now+600000u;invulnerable_until=now+1200000u;}
        else if(flash)flash_until=now+(games_phase==MISTAKE?450000u:games_phase==WATCH?500000u:230000u);
        return false;}
    if(game==PULSE){
        last_tick=now;
        if(games_phase==MISTAKE&&(int32_t)(now-flash_until)>=0){
            flash=sequence[0]+1u;entered=0;games_phase=WATCH;flash_until=now+500000u;
            sound_pending=(uint8_t)(5u+sequence[0]);++hud_revision;return true;
        }
        if(games_phase==WATCH&&(int32_t)(now-flash_until)>=0){
            if(flash){flash=0;flash_until=now+170000u;}
            else if(++entered<level){flash=sequence[entered]+1u;flash_until=now+430000u;
                sound_pending=(uint8_t)(5u+sequence[entered]);}
            else{entered=0;games_phase=PLAY;++hud_revision;}
            return true;
        }
        if(games_phase==PLAY&&flash&&(int32_t)(now-flash_until)>=0){flash=0;return true;}
        return false;
    }
    uint32_t elapsed=now-last_tick;if(elapsed<33333u)return false;if(elapsed>100000u)elapsed=100000u;last_tick=now;
    if(games_phase!=PLAY)return false;
    if(energy<100u){uint32_t charge=energy_carry+elapsed*25u;
        energy+=(uint16_t)(charge/1000000u);energy_carry=charge%1000000u;
        if(energy>100u)energy=100u;}
    if((int32_t)(now-spawn_at)>=0){
        for(uint32_t i=0;i<12u;++i)if(!rock[i].live){rock[i].live=1u;rock[i].x=(int16_t)(20u+random_next()%280u);
            rock[i].y=55;rock[i].fraction=0;rock[i].size=(uint8_t)(5u+random_next()%9u);break;}
        spawn_at=now+((score<80u?600u:score<200u?430u:300u)*1000u);
    }
    for(uint32_t i=0;i<12u;++i)if(rock[i].live){
        uint32_t speed=120u+(score<280u?score/2u:140u);
        uint32_t movement=rock[i].fraction+elapsed*speed;
        rock[i].y+=(int16_t)(movement/1000000u);rock[i].fraction=movement%1000000u;
        int32_t x=rock[i].x,y=rock[i].y,r=rock[i].size;
        if(y-r-2>203){rock[i].live=0u;if(score<65530u)score+=5u;}
        else if(x+r+2>(int32_t)ship-11&&x-r-2<(int32_t)ship+11&&
                y+r+2>167&&y-r-2<201&&
                (int32_t)(now-invulnerable_until)>=0){rock[i].live=0u;if(hearts)--hearts;sound_pending=3u;
            invulnerable_until=now+1200000u;if(!hearts){finish(false);break;}}
    }
    if(score!=old_score||hearts!=old_hearts||games_phase!=old_phase)++hud_revision;
    return true;
}
const char *ln_games_text(const char *key){
    if(key[5]=='t')return names[game];
    if(key[5]=='s'){
        char *p=score_text;append(&p,"Score ");number(&p,score);append(&p,"  Best ");number(&p,best[game]);
        if(game==PULSE){append(&p,"  Round ");number(&p,level);}
        append(&p,"  Lives ");number(&p,hearts);*p=0;return score_text;
    }
    if(key[5]=='o')return games_phase==PAUSED?"PAUSED":games_phase==LOST?"GAME OVER":games_phase==WON?"CLEARED":"";
    if(key[5]=='d')return games_phase==PAUSED?"Play to resume":games_phase==LOST?"Select to retry":games_phase==WON?"Select to replay":"";
    if(games_phase==PAUSED)return "PAUSED   Play: resume   Menu: Games";
    if(games_phase==LOST)return "GAME OVER   Select: retry   Menu: Games";
    if(games_phase==WON)return "CLEARED   Select: replay   Menu: Games";
    if(games_phase==MISTAKE)return "Wrong pad. Watch the pattern again";
    if(games_phase==WATCH)return "Watch the pattern, then repeat it";
    return game==COMET?"Wheel: steer  Select: shield  Play: pause":"Wheel: pick  Select: tap  Play: pause";
}
static void box(const struct ln_ui_canvas_context *c,int32_t x,int32_t y,int32_t w,int32_t h,uint16_t ink){
    int32_t left=x>c->clip_x?x:c->clip_x,top=y>c->clip_y?y:c->clip_y;
    int32_t right=x+w<c->clip_x+c->clip_w?x+w:c->clip_x+c->clip_w;
    int32_t bottom=y+h<c->clip_y+c->clip_h?y+h:c->clip_y+c->clip_h;
    if(left<0)left=0;if(top<0)top=0;if(right>320)right=320;if(bottom>240)bottom=240;
    for(int32_t yy=top;yy<bottom;++yy)for(int32_t xx=left;xx<right;++xx)c->pixels[yy*320+xx]=ink;
}
void ln_games_draw(const struct ln_ui_canvas_context *c){
    static const uint16_t pad[]={0xfca6u,0x35dbu,0xfec0u,0x9b5fu};
    box(c,0,203,320,1,0x2bd1u);
    for(uint32_t i=0;i<4u;++i){
        int32_t y=64+(int32_t)i*35;
        box(c,0,y,320,1,i&1u?0x1048u:0x186au);
        box(c,12+(int32_t)i*7,y-4,1,8,0x1870u);
        box(c,307-(int32_t)i*7,y-4,1,8,0x1870u);
    }
    if(game==COMET){
        for(uint32_t i=0;i<38u;++i){uint32_t x=(i*113u+37u)%320u,y=(i*71u+19u+last_tick/30000u*(i%3u+1u))%143u+59u;
            box(c,(int32_t)x,(int32_t)y,i%5u?1:2,i%5u?2:3,i%5u?0x6b9fu:0xa69fu);}
        for(uint32_t i=0;i<12u;++i)if(rock[i].live){int32_t x=rock[i].x,y=rock[i].y,r=rock[i].size;
            box(c,x-r-2,y-r-2,r*2+4,r*2+4,0x5069u);
            box(c,x-r,y-r,r*2,r*2,0xb9a9u);box(c,x-r+2,y-r+2,r*2-4,r*2-4,0xfaa8u);
            box(c,x-r+3,y-r+3,r-2,2,0xffdbu);box(c,x-2,y-2,4,4,0xffdbu);}
        bool bright=(int32_t)(last_tick-invulnerable_until)<0;
        if(bright){box(c,ship-17,166,12,2,0x4e9fu);box(c,ship+5,166,12,2,0x4e9fu);
            box(c,ship-17,168,2,25,0x4e9fu);box(c,ship+15,168,2,25,0x4e9fu);}
        if(!bright||((last_tick/90000u)&1u)==0){
            box(c,ship-10,190,20,3,0x2bd1u);box(c,ship-4,188,8,7,0x7fffu);
            for(int32_t y=0;y<19;++y)box(c,(int32_t)ship-y/2,186-y,y+2,1,bright?0xffffu:0x4e9fu);
            box(c,ship-3,182,6,5,0xffffu);
            uint32_t flame=4u+(last_tick/90000u)%8u;
            box(c,ship-2,193,4,(int32_t)flame,0xfbc0u);box(c,ship-1,193,2,(int32_t)flame/2,0xffffu);
        }
        box(c,238,198,68,3,0x184au);box(c,238,198,(int32_t)(energy*68u/100u),3,0x4e9fu);
    }else{
        for(uint32_t i=0;i<4u;++i){int32_t x=50+(int32_t)(i&1u)*116,y=66+(int32_t)(i>>1)*65;
            uint16_t ink=pad[i];box(c,x-5,y-5,94,56,0x0825u);
            box(c,x-3,y-3,90,52,i==focus&&games_phase==PLAY?0xffffu:0x39cdu);
            box(c,x,y,84,46,flash==i+1u?(games_phase==MISTAKE?0xf9a6u:0xffffu):ink);
            box(c,x+3,y+3,78,2,0xffffu);box(c,x+20,y+12,44,22,0x0825u);
            box(c,x+27,y+15,30,16,ink);box(c,x+3,y+40,78,3,0x186au);
        }
        box(c,50,195,220,4,0x184au);box(c,50,195,level*220u/24u,4,0x7fffu);
    }
    if(games_phase==PAUSED||games_phase==LOST||games_phase==WON){box(c,26,75,268,85,0x0843u);
        box(c,30,79,260,77,games_phase==PAUSED?0x218bu:games_phase==WON?0x354au:0x5069u);}
}

#if defined(LINNET_AUDIO)
static bool games_audio_owned;
void ln_games_audio_stop(void){if(games_audio_owned){(void)ln_audio_stop();games_audio_owned=false;}sound_pending=0;}
void ln_games_audio_step(void){
    struct ln_audio_status state;ln_audio_snapshot(&state);
    if(games_audio_owned&&!state.playing&&!sound_pending){ln_games_audio_stop();return;}
    if(!sound_pending||ln_player_busy())return;
    if(games_audio_owned&&state.playing)return;
    uint8_t cue=sound_pending;sound_pending=0;
    if(!ln_audio_init(22050u))return;
    games_audio_owned=true;
    int16_t pcm[512];uint32_t phase_value=0;
    uint32_t step=cue>=5u&&cue<=8u?0x04000000u+(cue-5u)*0x01000000u:
        cue==3u?0x03000000u:cue==4u?0x02000000u:cue==2u?0x08000000u:0x06000000u;
    for(uint32_t chunk=0;chunk<4u;++chunk){
        for(uint32_t i=0;i<256u;++i){
            uint32_t at=chunk*256u+i,wave=(phase_value>>23)&511u;
            int32_t triangle=(int32_t)(wave<256u?wave:511u-wave)-128;
            int16_t sample=(int16_t)((triangle*(int32_t)(1024u-at)*38)>>10);
            pcm[i*2u]=pcm[i*2u+1u]=sample;phase_value+=step;
        }
        if(ln_audio_submit(pcm,256u)!=256u){ln_games_audio_stop();return;}
    }
    ln_audio_finish();if(!ln_audio_start())ln_games_audio_stop();
}
#else
void ln_games_audio_step(void){}
void ln_games_audio_stop(void){sound_pending=0;}
#endif
