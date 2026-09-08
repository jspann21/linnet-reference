#include "kernel/shell.h"
#include "kernel/runtime.h"
#include "hal/pp5020/display.h"
#define W 220u
#define H 176u
#define BG 0xef7du
#define INK 0x18e5u
#define TEAL 0x04d0u
/* Five columns, seven rows; local fixed glyph data, no renderer allocation. */
static const uint8_t letters[26][5]={
 {0x7e,0x11,0x11,0x11,0x7e},{0x7f,0x49,0x49,0x49,0x36},
 {0x3e,0x41,0x41,0x41,0x22},{0x7f,0x41,0x41,0x22,0x1c},
 {0x7f,0x49,0x49,0x49,0x41},{0x7f,0x09,0x09,0x09,0x01},
 {0x3e,0x41,0x49,0x49,0x7a},{0x7f,0x08,0x08,0x08,0x7f},
 {0,0x41,0x7f,0x41,0},{0x20,0x40,0x41,0x3f,0x01},
 {0x7f,0x08,0x14,0x22,0x41},{0x7f,0x40,0x40,0x40,0x40},
 {0x7f,0x02,0x0c,0x02,0x7f},{0x7f,0x04,0x08,0x10,0x7f},
 {0x3e,0x41,0x41,0x41,0x3e},{0x7f,0x09,0x09,0x09,0x06},
 {0x3e,0x41,0x51,0x21,0x5e},{0x7f,0x09,0x19,0x29,0x46},
 {0x46,0x49,0x49,0x49,0x31},{0x01,0x01,0x7f,0x01,0x01},
 {0x3f,0x40,0x40,0x40,0x3f},{0x1f,0x20,0x40,0x20,0x1f},
 {0x3f,0x40,0x38,0x40,0x3f},{0x63,0x14,0x08,0x14,0x63},
 {0x07,0x08,0x70,0x08,0x07},{0x61,0x51,0x49,0x45,0x43}};
static const char *const titles[4]={"DISPLAY","INPUT","POWER","SYSTEM"};
static void rect(uint16_t*p,uint32_t x,uint32_t y,uint32_t w,uint32_t h,uint16_t color){
    if(x>=W||y>=H)return;if(w>W-x)w=W-x;if(h>H-y)h=H-y;
    for(uint32_t row=y;row<y+h;++row)for(uint32_t col=x;col<x+w;++col)p[row*W+col]=color;
}
static void text(uint16_t*p,uint32_t x,uint32_t y,const char*s,uint16_t color,uint32_t scale){
    for(uint32_t n=0;s[n]&&n<32;++n,x+=6u*scale){
        if(s[n]<'A'||s[n]>'Z')continue;
        for(uint32_t c=0;c<5;++c)for(uint32_t r=0;r<7;++r)
            if(letters[(unsigned)(s[n]-'A')][c]&(1u<<r))rect(p,x+c*scale,y+r*scale,scale,scale,color);
    }
}
void ln_shell_init(ln_shell*s){s->selected=s->scene=s->animation=s->buttons=0;s->hold=s->headphones=s->rendered=false;s->drawn_selected=s->drawn_scene=0;s->drawn_hold=s->drawn_headphones=false;}
bool ln_shell_input(ln_shell*s,uint32_t kind,int32_t value){
    if(kind==LN_INPUT_HOLD){bool changed=s->hold!=(value!=0);s->hold=value!=0;return changed;}
    if(kind==LN_INPUT_HEADPHONE){bool changed=s->headphones!=(value!=0);s->headphones=value!=0;return changed;}
    if(kind==LN_INPUT_BUTTON){uint32_t pressed=(uint32_t)value&~s->buttons;s->buttons=(uint32_t)value;
        if(s->hold||!pressed)return false;
        if(pressed&LN_BUTTON_MENU){s->scene=0;return true;}
        if(pressed&LN_BUTTON_SELECT){s->scene=s->selected+1u;return true;}
        if(pressed&LN_BUTTON_NEXT){s->selected=(s->selected+1u)&3u;if(s->scene)s->scene=s->selected+1u;return true;}
        if(pressed&LN_BUTTON_PREV){s->selected=(s->selected+3u)&3u;if(s->scene)s->scene=s->selected+1u;return true;}
        return false;
    }
    if(kind==LN_INPUT_WHEEL&&!s->hold&&value){s->selected=(s->selected+(uint32_t)value)&3u;return true;}
    return false;
}
void ln_shell_render(ln_shell*s,uint16_t*p){
    if(s->rendered&&!s->scene&&!s->drawn_scene&&s->hold==s->drawn_hold&&s->headphones==s->drawn_headphones){
        for(uint32_t i=0;i<4;++i)if(i==s->selected||i==s->drawn_selected){
            uint32_t y=38u+27u*i;rect(p,10,y,200,23,i==s->selected?TEAL:BG);
            text(p,18,y+5,titles[i],i==s->selected?0xffffu:INK,2);ln_display_damage(10,(int32_t)y,200,23);
        }
        s->drawn_selected=s->selected;return;
    }
    rect(p,0,0,W,H,BG);rect(p,0,0,W,28,INK);text(p,12,7,"LINNET",0xffffu,2);
    if(!s->scene){
        for(uint32_t i=0;i<4;++i){uint32_t y=38u+27u*i;
            if(i==s->selected)rect(p,10,y,200,23,TEAL);
            text(p,18,y+5,titles[i],i==s->selected?0xffffu:INK,2);
        }
    }else{
        text(p,12,43,titles[s->scene-1u],INK,2);
        const char*line=s->scene==1?"FRAMEBUFFER READY":s->scene==2?"WHEEL AND BUTTONS":s->scene==3?"POWER CONTROL":"NATIVE PLATFORM";
        text(p,12,72,line,INK,1);text(p,12,94,"MENU TO RETURN",TEAL,1);
#if defined(LINNET_STORAGE)
        if(s->scene==4)text(p,12,116,"SELECT FOR USB SYNC",TEAL,1);
#endif
    }
    rect(p,0,154,W,22,INK);text(p,10,161,s->hold?"HOLD":"READY",0xffffu,1);
    if(s->headphones)text(p,134,161,"HEADPHONES",0xffffu,1);
    ln_display_damage(0,0,W,H);
    s->rendered=true;s->drawn_selected=s->selected;s->drawn_scene=s->scene;
    s->drawn_hold=s->hold;s->drawn_headphones=s->headphones;
}
void ln_shell_animate(ln_shell*s,uint16_t*p,uint32_t frame){
    rect(p,10,145,200,7,BG);rect(p,10+(frame%40u)*5u,145,5,7,TEAL);s->animation=frame;
    ln_display_damage(10,145,200,7);
}
