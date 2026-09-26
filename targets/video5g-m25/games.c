#include "targets/video5g-m25/games.h"
#if defined(LINNET_AUDIO)
#include "hal/api/audio.h"
#include "services/music/player.h"
#endif
#if defined(LINNET_STORAGE)
#include "services/display/settings.h"
#endif
#include "targets/video5g-m25/solitaire_courts.h"

enum { COMET, PULSE, SOLITAIRE, GAME_COUNT };
enum { PLAY=1u, PAUSED, LOST, WATCH, MISTAKE, WON, ARCADE_READY };
static uint8_t installed=7u,game,games_phase,paused_phase,hearts,focus,sequence[24],entered,level,flash;
static uint16_t ship=160,energy,score,best[GAME_COUNT];
static uint32_t random_state=0x9e3779b9u,last_tick,spawn_at,flash_until,invulnerable_until,hud_revision,energy_carry;
static uint32_t buttons;
static uint8_t sound_pending;
static bool resume_pending;
static uint32_t hit_until,shield_notice_until;
static bool shield_failed;
static uint16_t previous_best;
static uint32_t burst_until;
static int16_t burst_x,burst_y;
static bool burst_shield;
static struct {int16_t x,y;uint8_t size,live;uint32_t fraction;} rock[12];
static char score_text[48];
static const char *const names[]={"Comet Run","Pulse Path","Solitaire"};
static uint32_t random_next(void);

/* Draw-one Klondike. Piles use their last element as the top card. A tableau
 * source index can name any face-up card, moving that card and everything above. */
static uint8_t sol_stock[52],sol_waste[52],sol_tableau[7][52];
static uint8_t sol_stock_count,sol_waste_count,sol_count[7],sol_hidden[7],sol_foundation[4];
static uint8_t sol_cursor,sol_depth,sol_source=255u,sol_source_depth;
static uint16_t sol_moves;
static uint8_t sol_rank(uint8_t card){return (uint8_t)(card%13u+1u);}
static uint8_t sol_suit(uint8_t card){return card/13u;}
static bool sol_red(uint8_t card){uint8_t suit=sol_suit(card);return suit==1u||suit==2u;}
static void sol_focus(uint8_t spot){
    sol_cursor=spot;
    if(spot>=6u){uint8_t col=(uint8_t)(spot-6u);sol_depth=sol_count[col]?sol_count[col]-1u:0u;}
}
static void sol_new(void){
    uint8_t deck[52];for(uint8_t i=0;i<52u;++i)deck[i]=i;
    for(uint32_t i=51u;i;i--){uint32_t j=random_next()%(i+1u);uint8_t swap=deck[i];deck[i]=deck[j];deck[j]=swap;}
    uint32_t next=0;for(uint8_t col=0;col<7u;++col){
        sol_count[col]=col+1u;sol_hidden[col]=col;
        for(uint8_t at=0;at<=col;++at)sol_tableau[col][at]=deck[next++];
    }
    sol_stock_count=24u;sol_waste_count=0u;
    for(uint8_t i=0;i<24u;++i)sol_stock[i]=deck[next++];
    for(uint8_t i=0;i<4u;++i)sol_foundation[i]=0u;
    sol_source=255u;sol_source_depth=0u;sol_moves=0u;sol_focus(0u);
}
static void sol_win(void){
    for(uint8_t i=0;i<4u;++i)if(sol_foundation[i]!=13u)return;
    games_phase=WON;sound_pending=4u;
    if(best[SOLITAIRE]!=UINT16_MAX){++best[SOLITAIRE];
#if defined(LINNET_STORAGE)
        ln_display_game_best_set(SOLITAIRE,best[SOLITAIRE]);
#endif
    }
}
static bool sol_draw(void){
    if(sol_stock_count){sol_waste[sol_waste_count++]=sol_stock[--sol_stock_count];++sol_moves;sound_pending=2u;return true;}
    if(!sol_waste_count)return false;
    while(sol_waste_count)sol_stock[sol_stock_count++]=sol_waste[--sol_waste_count];
    ++sol_moves;sound_pending=2u;return true;
}
static bool sol_select_source(void){
    if(sol_cursor==1u&&!sol_waste_count)return false;
    if(sol_cursor>=2u&&sol_cursor<6u&&!sol_foundation[sol_cursor-2u])return false;
    if(sol_cursor>=6u){uint8_t col=(uint8_t)(sol_cursor-6u);
        if(!sol_count[col]||sol_depth<sol_hidden[col]||sol_depth>=sol_count[col])return false;
    }
    sol_source=sol_cursor;sol_source_depth=sol_depth;sound_pending=1u;return true;
}
static bool sol_move(void){
    uint8_t source=sol_source,dest=sol_cursor,first,count,card;
    if(source==255u||source==dest||dest==0u||dest==1u)return false;
    if(source==1u){first=(uint8_t)(sol_waste_count-1u);count=1u;card=sol_waste[first];}
    else if(source<6u){first=0u;count=1u;card=(uint8_t)((source-2u)*13u+sol_foundation[source-2u]-1u);}
    else {uint8_t col=(uint8_t)(source-6u);first=sol_source_depth;
        count=(uint8_t)(sol_count[col]-first);card=sol_tableau[col][first];}
    if(dest<6u){uint8_t suit=(uint8_t)(dest-2u);
        if(count!=1u||sol_suit(card)!=suit||sol_rank(card)!=sol_foundation[suit]+1u)return false;
    }else{uint8_t col=(uint8_t)(dest-6u),length=sol_count[col];
        if(length>=52u-count+1u)return false;
        if(length){uint8_t top=sol_tableau[col][length-1u];
            if(sol_red(top)==sol_red(card)||sol_rank(top)!=sol_rank(card)+1u)return false;
        }else if(sol_rank(card)!=13u)return false;
    }
    if(dest<6u)++sol_foundation[dest-2u];
    else {uint8_t col=(uint8_t)(dest-6u);
        for(uint8_t i=0;i<count;++i)sol_tableau[col][sol_count[col]++]=source==1u?card:
            source<6u?card:sol_tableau[source-6u][first+i];
    }
    if(source==1u)--sol_waste_count;
    else if(source<6u)--sol_foundation[source-2u];
    else {uint8_t col=(uint8_t)(source-6u);sol_count[col]=first;
        if(sol_count[col]&&sol_hidden[col]==sol_count[col]){--sol_hidden[col];sound_pending=5u;}
        else sound_pending=2u;
    }
    ++sol_moves;sol_source=255u;sol_focus(dest);sol_win();return true;
}

static uint32_t random_next(void){random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;return random_state;}
static void number(char **out,uint32_t value){char reverse[10];uint32_t n=0;do{reverse[n++]=(char)('0'+value%10u);value/=10u;}while(value);while(n)*(*out)++=reverse[--n];}
static void append(char **out,const char *text){while(*text)*(*out)++=*text++;}
uint32_t ln_games_count(void){return (installed&1u?1u:0u)+(installed&2u?1u:0u)+(installed&4u?1u:0u);}
const char *ln_games_label(uint32_t row){for(uint32_t i=0;i<GAME_COUNT;++i)if(installed&(1u<<i)){if(!row)return names[i];--row;}return 0;}
const char *ln_games_description(uint32_t row){
    for(uint32_t i=0;i<GAME_COUNT;++i)if(installed&(1u<<i)){
        if(!row)return i==COMET?"Thread through the meteor field.":
            i==PULSE?"Remember the lights. Find the path.":"Build four suits from Ace to King.";
        --row;
    }
    return "Choose games in Linnet Media.";
}
void ln_games_configure(uint8_t mask){installed=mask&7u;}
void ln_games_best_set(uint32_t index,uint16_t value){if(index<GAME_COUNT)best[index]=value;}
bool ln_games_playing(void){return game!=SOLITAIRE&&(games_phase==PLAY||games_phase==WATCH||games_phase==MISTAKE);}
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
    flash=0;entered=255u;flash_until=last_tick+700000u;games_phase=WATCH;
}
void ln_games_start(uint32_t row){
    for(uint32_t i=0;i<GAME_COUNT;++i)if(installed&(1u<<i)){if(!row){game=(uint8_t)i;break;}--row;}
    random_state^=last_tick+0x6d2b79f5u;games_phase=paused_phase=PLAY;score=0;hearts=3u;focus=0u;sound_pending=1u;
    resume_pending=false;
    hit_until=shield_notice_until=burst_until=0;shield_failed=false;previous_best=best[game];
    if(game==COMET){ship=160u;energy=100u;energy_carry=0;spawn_at=last_tick+600000u;invulnerable_until=last_tick+1200000u;for(uint32_t i=0;i<12u;++i)rock[i].live=0;}
    else if(game==PULSE){level=0u;new_pulse();}
    else sol_new();
    if(game!=SOLITAIRE)games_phase=ARCADE_READY;
    last_tick=0;++hud_revision;
}
static void finish(bool won){games_phase=won?WON:LOST;sound_pending=4u;if(score>best[game]){
        best[game]=score;
#if defined(LINNET_STORAGE)
        ln_display_game_best_set(game,score);
#endif
    }}
int ln_games_input(uint32_t kind,int32_t value){
    if(kind==1u){if(!value)return 1;if(games_phase==PLAY&&game==SOLITAIRE){
            int32_t next=(int32_t)sol_cursor+value%13;
            while(next<0)next+=13;while(next>=13)next-=13;
            sol_focus((uint8_t)next);++hud_revision;return 1;
        }if(games_phase==PLAY&&game==COMET){
            int32_t steps=value<-24?-24:value>24?24:value;
            int32_t next=(int32_t)ship+steps*6;if(next<18)next=18;if(next>302)next=302;ship=(uint16_t)next;}
        else if(games_phase==PLAY&&game==PULSE)focus=(uint8_t)((focus+value%4+4)&3u);return 1;}
    if(kind!=2u)return 0;
    uint32_t pressed=(uint32_t)value&~buttons;buttons=(uint32_t)value;
    if(pressed&1u)return 2;
    if(games_phase==ARCADE_READY){if(pressed&16u){games_phase=game==COMET?PLAY:WATCH;last_tick=0;++hud_revision;}return 1;}
    if(pressed&2u){if(games_phase==PLAY||games_phase==WATCH||games_phase==MISTAKE){paused_phase=games_phase;games_phase=PAUSED;}
        else if(games_phase==PAUSED){games_phase=paused_phase;resume_pending=true;}return 1;}
    if(game==SOLITAIRE&&games_phase==PAUSED&&(pressed&16u)){
        uint32_t row=0;for(uint32_t i=0;i<game;++i)if(installed&(1u<<i))++row;
        ln_games_start(row);return 1;}
    if((games_phase==LOST||games_phase==WON)&&(pressed&16u)){
        uint32_t row=0;for(uint32_t i=0;i<game;++i)if(installed&(1u<<i))++row;
        ln_games_start(row);if(game!=SOLITAIRE)games_phase=game==COMET?PLAY:WATCH;return 1;}
    if(games_phase!=PLAY)return 1;
    if(game==SOLITAIRE){
        if(sol_cursor>=6u&&sol_source==255u){uint8_t col=(uint8_t)(sol_cursor-6u);
            if((pressed&8u)&&sol_depth>sol_hidden[col]){--sol_depth;++hud_revision;}
            if((pressed&4u)&&sol_depth+1u<sol_count[col]){++sol_depth;++hud_revision;}
        }
        if(pressed&16u){bool changed=false;
            if(sol_source==255u)changed=sol_cursor==0u?sol_draw():sol_select_source();
            else if(sol_source==sol_cursor){sol_source=255u;changed=true;}
            else changed=sol_move();
            if(changed)++hud_revision;else sound_pending=3u;
        }
    }else if(game==COMET){
        if(pressed&4u)ship=ship<286u?ship+16u:302u;
        if(pressed&8u)ship=ship>34u?ship-16u:18u;
        if((pressed&16u)&&energy>=40u){energy-=40u;
            shield_failed=false;shield_notice_until=last_tick+800000u;
            uint32_t shield_until=last_tick+800000u;
            if((int32_t)(shield_until-invulnerable_until)>0)invulnerable_until=shield_until;
            sound_pending=2u;}
        else if(pressed&16u){shield_failed=true;shield_notice_until=last_tick+600000u;sound_pending=3u;}
    }else{
        if(pressed&4u)focus=(focus+1u)&3u;
        if(pressed&8u)focus=(focus+3u)&3u;
        if((pressed&16u)&&entered<level){
            flash=focus+1u;flash_until=last_tick+230000u;
            if(focus!=sequence[entered]){
                sound_pending=3u;if(hearts)--hearts;++hud_revision;
                if(!hearts)finish(false);
                else{entered=0;games_phase=MISTAKE;flash_until=last_tick+450000u;}
            }else {sound_pending=(uint8_t)(5u+focus);++entered;++hud_revision;}
        }
    }
    return 1;
}
bool ln_games_tick(uint32_t now){
    if(!games_phase){last_tick=now;return false;}
    if(game==SOLITAIRE)return false;
    uint16_t old_score=score;uint8_t old_hearts=hearts,old_phase=games_phase;
    if(games_phase==PAUSED||games_phase==ARCADE_READY)return false;
    if(resume_pending){resume_pending=false;
        if(last_tick){uint32_t paused_for=now-last_tick;
            if(game==COMET){spawn_at+=paused_for;invulnerable_until+=paused_for;
                if(hit_until)hit_until+=paused_for;if(shield_notice_until)shield_notice_until+=paused_for;
                if(burst_until)burst_until+=paused_for;}
            else flash_until+=paused_for;
            last_tick=now;return false;
        }
    }
    if(!last_tick){last_tick=now;
        if(game==COMET){spawn_at=now+600000u;invulnerable_until=now+1200000u;}
        else if(flash||games_phase==WATCH)flash_until=now+(games_phase==MISTAKE?450000u:games_phase==WATCH?700000u:230000u);
        return false;}
    if(game==PULSE){
        last_tick=now;
        if(games_phase==MISTAKE&&(int32_t)(now-flash_until)>=0){
            flash=sequence[0]+1u;entered=0;games_phase=WATCH;flash_until=now+500000u;
            sound_pending=(uint8_t)(5u+sequence[0]);++hud_revision;return true;
        }
        if(games_phase==WATCH&&(int32_t)(now-flash_until)>=0){
            if(flash){flash=0;flash_until=now+170000u;}
            else if(entered==255u||entered+1u<level){entered=entered==255u?0u:(uint8_t)(entered+1u);flash=sequence[entered]+1u;flash_until=now+500000u;
                sound_pending=(uint8_t)(5u+sequence[entered]);}
            else{entered=0;games_phase=PLAY;++hud_revision;}
            return true;
        }
        if(games_phase==PLAY&&flash&&(int32_t)(now-flash_until)>=0){flash=0;
            if(entered==level){score+=level*10u;new_pulse();++hud_revision;}return true;}
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
                y+r+2>167&&y-r-2<201){
            rock[i].live=0u;burst_x=(int16_t)x;burst_y=(int16_t)y;burst_until=now+350000u;
            burst_shield=(int32_t)(now-invulnerable_until)<0;
            if(burst_shield){if(score<65530u)score+=5u;sound_pending=2u;continue;}
            if(hearts)--hearts;sound_pending=3u;
            hit_until=now+350000u;invulnerable_until=now+1200000u;if(!hearts){finish(false);break;}}
    }
    if(score!=old_score||hearts!=old_hearts||games_phase!=old_phase)++hud_revision;
    return true;
}
const char *ln_games_text(const char *key){
    if(game!=SOLITAIRE)return ""; /* Arcade canvas owns its HUD and result layout. */
    if(key[5]=='t')return names[game];
    if(key[5]=='s'){
        if(game==SOLITAIRE){char *p=score_text;append(&p,"Moves ");number(&p,sol_moves);
            append(&p,"  Wins ");number(&p,best[SOLITAIRE]);
            uint8_t spot=sol_source!=255u?sol_source:sol_cursor,card=255u;
            uint8_t depth=sol_source!=255u?sol_source_depth:sol_depth;
            if(spot==1u&&sol_waste_count)card=sol_waste[sol_waste_count-1u];
            else if(spot>=2u&&spot<6u&&sol_foundation[spot-2u])
                card=(uint8_t)((spot-2u)*13u+sol_foundation[spot-2u]-1u);
            else if(spot>=6u&&depth<sol_count[spot-6u]&&depth>=sol_hidden[spot-6u])
                card=sol_tableau[spot-6u][depth];
            if(card<52u){static const char *const suits[]={"Clubs","Diamonds","Hearts","Spades"};
                append(&p,"  ");uint8_t rank=sol_rank(card);
                if(rank==1u)*p++='A';else if(rank==11u)*p++='J';else if(rank==12u)*p++='Q';
                else if(rank==13u)*p++='K';else number(&p,rank);
                *p++=' ';append(&p,suits[sol_suit(card)]);
            }
            *p=0;return score_text;}
        char *p=score_text;append(&p,"Score ");number(&p,score);append(&p,"  Best ");number(&p,best[game]);
        if(game==PULSE){append(&p,"  Round ");number(&p,level);}
        append(&p,"  Lives ");number(&p,hearts);*p=0;return score_text;
    }
    if(key[5]=='o')return games_phase==PAUSED?"PAUSED":games_phase==LOST?"GAME OVER":games_phase==WON?"CLEARED":"";
    if(key[5]=='d')return games_phase==PAUSED?game==SOLITAIRE?"Select: new deal":"Play to resume":games_phase==LOST?"Select to retry":games_phase==WON?"Select to replay":"";
    if(games_phase==PAUSED)return game==SOLITAIRE?"PAUSED  Play: resume  Select: new deal":"PAUSED   Play: resume   Menu: Games";
    if(games_phase==LOST)return "GAME OVER   Select: retry   Menu: Games";
    if(games_phase==WON)return game==SOLITAIRE?"SOLVED   Select: new deal   Menu: Games":"CLEARED   Select: replay   Menu: Games";
    if(game==SOLITAIRE)return sol_source!=255u?"Wheel: target  Select: move/cancel":"Wheel: pile  </>: card  Select: pick";
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
static void sol_glyph(const struct ln_ui_canvas_context *c,int32_t x,int32_t y,char ch,uint16_t ink){
    static const char letters[]="A23456789TJQK10";
    static const uint8_t bits[15][7]={
        {14,17,17,31,17,17,17},{14,17,1,6,8,16,31},
        {30,1,1,14,1,1,30},{2,6,10,18,31,2,2},
        {31,16,30,1,1,17,14},{7,8,16,30,17,17,14},
        {31,1,2,4,8,8,8},{14,17,17,14,17,17,14},
        {14,17,17,15,1,2,28},{31,4,4,4,4,4,4},
        {7,2,2,2,18,18,12},{14,17,17,17,21,18,13},
        {17,18,20,24,20,18,17},{4,12,4,4,4,4,14},
        {14,17,19,21,25,17,14}
    };
    uint8_t at=0;while(at<15u&&letters[at]!=ch)++at;if(at==15u)return;
    for(uint8_t row=0;row<7u;++row)for(uint8_t col=0;col<5u;++col)
        if(bits[at][row]&(16u>>col))box(c,x+col,y+row,1,1,ink);
}
static void sol_outline(const struct ln_ui_canvas_context *c,int32_t x,int32_t y,int32_t h,uint16_t ink){
    box(c,x-2,y-2,42,2,ink);box(c,x-2,y+h,42,2,ink);
    box(c,x-2,y,2,h,ink);box(c,x+38,y,2,h,ink);
}
static void sol_suit_mark(const struct ln_ui_canvas_context *c,int32_t x,int32_t y,uint8_t suit,uint8_t scale,uint16_t ink){
    static const uint8_t bits[4][7]={
        {8,28,8,119,127,28,8},
        {8,28,62,127,62,28,8},
        {54,127,127,127,62,28,8},
        {8,28,62,127,119,8,28}
    };
    for(uint8_t row=0;row<7u;++row)for(uint8_t col=0;col<7u;++col)
        if(bits[suit][row]&(64u>>col))box(c,x+col*scale,y+row*scale,scale,scale,ink);
}
static void sol_small_suit(const struct ln_ui_canvas_context *c,int32_t x,int32_t y,uint8_t suit,uint16_t ink){
    static const uint8_t bits[4][5]={
        {4,14,21,14,4},{4,14,31,14,4},
        {10,31,31,14,4},{4,14,31,21,4}
    };
    for(uint8_t row=0;row<5u;++row)for(uint8_t col=0;col<5u;++col)
        if(bits[suit][row]&(16u>>col))box(c,x+col,y+row,1,1,ink);
}
static void sol_court_card(const struct ln_ui_canvas_context *c,int32_t x,int32_t y,uint8_t rank,uint8_t suit){
    const uint8_t *pixels=sol_court_pixels[suit*3u+rank-11u];
    for(int32_t row=0;row<50;++row){
        int32_t yy=y+row;
        if(yy<0||yy>=240||yy<c->clip_y||yy>=c->clip_y+c->clip_h)continue;
        for(int32_t col=0;col<38;++col){
            int32_t xx=x+col;
            if(xx<0||xx>=320||xx<c->clip_x||xx>=c->clip_x+c->clip_w)continue;
            c->pixels[yy*320+xx]=sol_court_palette[pixels[row*38+col]];
        }
    }
}
static void sol_card(const struct ln_ui_canvas_context *c,int32_t x,int32_t y,uint8_t card,bool back,int32_t height){
    box(c,x+1,y+1,38,height,0x02c2u);
    if(!back&&height>=50&&sol_rank(card)>=11u){sol_court_card(c,x,y,sol_rank(card),sol_suit(card));return;}
    box(c,x,y,38,height,back?0xffffu:0xc618u);
    box(c,x+1,y+1,36,height>2?height-2:1,back?0x2254u:0xffffu);
    if(back){
        box(c,x+3,y+3,32,height>6?height-6:1,0x54f9u);
        for(int32_t dx=5;dx<34;dx+=6)for(int32_t dy=5;dy<height-4;dy+=6){
            box(c,x+dx,y+dy,2,2,0xffffu);box(c,x+dx+2,y+dy+2,2,2,0x1a4du);
        }
        return;
    }
    uint16_t ink=sol_red(card)?0xd0c3u:0x18a7u;
    uint8_t rank=sol_rank(card),suit=sol_suit(card);
    if(rank==10u){sol_glyph(c,x+3,y+3,'1',ink);sol_glyph(c,x+9,y+3,'0',ink);}
    else sol_glyph(c,x+3,y+3,"A23456789TJQK"[rank-1u],ink);
    if(height>=9)sol_small_suit(c,x+(rank==10u?17:11),y+4,suit,ink);
    if(height<30)return;
    if(rank==1u)sol_suit_mark(c,x+12,y+24,suit,2u,ink);
    else if(rank>=11u)sol_suit_mark(c,x+12,y+24,suit,2u,ink);
    else {static const uint8_t slot_x[]={15,15,15,6,25,6,25,6,25,15,15};
        static const uint8_t slot_y[]={16,26,37,15,15,26,26,37,37,22,32};
        static const uint8_t layout[9][10]={
            {0,2,255},{0,1,2,255},{3,4,7,8,255},{3,4,1,7,8,255},
            {3,4,5,6,7,8,255},{3,4,5,6,7,8,0,255},
            {3,4,5,6,7,8,0,2,255},{3,4,5,6,7,8,0,1,2,255},
            {3,4,5,6,7,8,0,9,10,2}
        };
        for(uint8_t i=0;i<10u&&layout[rank-2u][i]!=255u;++i){uint8_t slot=layout[rank-2u][i];
            sol_small_suit(c,x+slot_x[slot],y+slot_y[slot],suit,ink);}
    }
}
static void sol_draw_board(const struct ln_ui_canvas_context *c){
    static const int16_t top_x[6]={7,51,139,183,227,271};
    box(c,0,43,320,172,0x1b48u);
    for(uint8_t spot=0;spot<6u;++spot){int32_t x=top_x[spot],y=49;
        box(c,x,y,38,50,0x340du);box(c,x+1,y+1,36,48,0x1b48u);
        if(spot==0u&&sol_stock_count)sol_card(c,x,y,0,true,50);
        else if(spot==1u&&sol_waste_count)sol_card(c,x,y,sol_waste[sol_waste_count-1u],false,50);
        else if(spot>=2u){uint8_t suit=(uint8_t)(spot-2u),rank=sol_foundation[suit];
            if(rank)sol_card(c,x,y,(uint8_t)(suit*13u+rank-1u),false,50);
            else sol_suit_mark(c,x+12,y+18,suit,2u,suit==1u||suit==2u?0x9045u:0x3a12u);
        }
        if(sol_cursor==spot)sol_outline(c,x,y,50,0xffc0u);
        if(sol_source==spot)sol_outline(c,x,y,50,0x07ffu);
    }
    for(uint8_t col=0;col<7u;++col){
        int32_t x=7+(int32_t)col*44,y=106,step=13;
        uint8_t length=sol_count[col];
        if(length>5u){step=60/(length-1u);if(step<3)step=3;}
        if(!length){box(c,x,y,38,50,0x340du);box(c,x+1,y+1,36,48,0x1b48u);}
        for(uint8_t i=0;i<length;++i){int32_t at=y+(int32_t)i*step;
            if(at>165)at=165;
            sol_card(c,x,at,sol_tableau[col][i],i<sol_hidden[col],i+1u<length?step:50);
        }
        int32_t selected_y=length?y+(int32_t)sol_depth*step:y;
        if(selected_y>165)selected_y=165;
        if(sol_cursor==col+6u)sol_outline(c,x,selected_y,length?sol_depth+1u<length?step:50:50,0xffc0u);
        if(sol_source==col+6u){int32_t sy=y+(int32_t)sol_source_depth*step;
            if(sy>165)sy=165;sol_outline(c,x,sy,sol_source_depth+1u<length?step:50,0x07ffu);}
    }
}
#include "targets/video5g-m25/games_arcade.h"
void ln_games_draw(const struct ln_ui_canvas_context *c){
    if(game==SOLITAIRE){
        box(c,0,0,320,43,0x1167u);box(c,0,215,320,25,0x1167u);
        sol_draw_board(c);
        if(games_phase==PAUSED||games_phase==WON){box(c,76,88,168,60,0x0843u);
            box(c,80,92,160,52,games_phase==PAUSED?0x218bu:0x354au);}
        return;
    }
    arcade_draw(c);
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
