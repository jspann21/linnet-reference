/* Fixed-size, allocation-free arcade artwork. Uses the native antialiased fonts. */
static uint16_t arcade_mix(uint16_t a,uint16_t b,uint32_t t){
    uint32_t z=255u-t;
    return (uint16_t)(((((a>>11)*t+(b>>11)*z)/255u)<<11)|
        (((((a>>5)&63u)*t+((b>>5)&63u)*z)/255u)<<5)|(((a&31u)*t+(b&31u)*z)/255u));
}
static void arcade_text(const struct ln_ui_canvas_context *c,int32_t x,int32_t y,const char *s,uint16_t ink,bool small){
    const struct ln_ui_font *f=small?&ln_ui_hint_font:&ln_ui_font;
    for(;*s;++s){uint32_t ch=(uint8_t)*s;if(ch<f->first||ch-f->first>=f->count)continue;
        uint32_t n=ch-f->first,w=f->width,h=f->height,offset=n*w*h;int32_t gx=x,gy=y;
        if(f->glyphs){const struct ln_ui_glyph *g=&f->glyphs[n];w=g->w;h=g->h;offset=g->offset;gx+=g->x;gy+=g->y;}
        for(uint32_t yy=0;yy<h;++yy)for(uint32_t xx=0;xx<w;++xx){int32_t px=gx+(int32_t)xx,py=gy+(int32_t)yy;
            if(px<0||px>=320||py<0||py>=240||px<c->clip_x||px>=c->clip_x+c->clip_w||py<c->clip_y||py>=c->clip_y+c->clip_h||px<c->x||px>=c->x+c->w||py<c->y||py>=c->y+c->h)continue;
            uint32_t a=f->alpha[offset+yy*w+xx];if(a)c->pixels[py*320+px]=arcade_mix(ink,c->pixels[py*320+px],a);
        }
        x+=(int32_t)(f->advances?f->advances[n]:f->advance);
    }
}
static void arcade_value(const struct ln_ui_canvas_context *c,int32_t x,int32_t y,uint32_t value,uint16_t ink){
    char text[12],*p=text;number(&p,value);*p=0;arcade_text(c,x,y,text,ink,false);
}
static void arcade_panel(const struct ln_ui_canvas_context *c,int32_t x,int32_t y,int32_t w,int32_t h,uint16_t ink){
    box(c,x+3,y,w-6,h,ink);box(c,x,y+3,w,h-6,ink);box(c,x+1,y+1,w-2,h-2,ink);
}
static void arcade_disc(const struct ln_ui_canvas_context *c,int32_t x,int32_t y,int32_t r,uint16_t ink){
    for(int32_t dy=-r;dy<=r;++dy){int32_t dx=r;while(dx*dx+dy*dy>r*r)--dx;box(c,x-dx,y+dy,dx*2+1,1,ink);}
}
static void arcade_lives(const struct ln_ui_canvas_context *c){
    for(uint32_t i=0;i<3u;++i){int32_t x=268+(int32_t)i*16;uint16_t ink=i<hearts?0xfbceu:0x294bu;
        box(c,x,12,4,3,ink);box(c,x+6,12,4,3,ink);box(c,x,15,10,3,ink);
        box(c,x+2,18,6,2,ink);box(c,x+4,20,2,2,ink);}
}
static void arcade_symbol(const struct ln_ui_canvas_context *c,int32_t x,int32_t y,uint32_t i,uint16_t ink){
    if(i==0u){for(int32_t r=0;r<11;++r)box(c,x-r,y-10+r,2*r+1,1,ink);}
    else if(i==1u){arcade_disc(c,x,y-2,9,ink);arcade_disc(c,x,y-2,5,0x10a7u);}
    else if(i==2u){for(int32_t r=-10;r<=10;++r){int32_t w=10-(r<0?-r:r);box(c,x-w,y+r-2,w*2+1,1,ink);}}
    else{box(c,x-9,y-11,18,18,ink);box(c,x-5,y-7,10,10,0x10a7u);}
}
static void arcade_draw(const struct ln_ui_canvas_context *c){
    const uint16_t navy=0x0865u,muted=0x94d6u,white=0xefbfu,cyan=0x6f5du;
    box(c,0,0,320,240,navy);box(c,0,0,320,31,0x10e8u);
    arcade_text(c,12,6,names[game],white,false);arcade_lives(c);
    box(c,0,30,320,1,0x294bu);
    if(game==COMET){
        arcade_text(c,12,36,"SCORE",muted,true);arcade_value(c,53,33,score,white);
        arcade_text(c,114,36,"BEST",muted,true);arcade_value(c,148,33,best[game],cyan);
        bool notice=shield_notice_until&&(int32_t)(last_tick-shield_notice_until)<0;
        arcade_text(c,219,36,notice?(shield_failed?"NEED 40%":"SHIELD ON"):energy>=40u?"SHIELD READY":"RECHARGING",notice&&shield_failed?0xfd4bu:energy>=40u||notice?cyan:muted,true);
        box(c,220,51,88,3,0x294bu);box(c,220,51,(int32_t)(energy*88u/100u),3,cyan);
        box(c,255,50,1,5,white);
        const struct ln_ui_canvas_context *full=c;
        struct ln_ui_canvas_context field=*c;
        int32_t bottom=c->clip_y+c->clip_h;if(bottom>207)bottom=207;
        if(field.clip_y<58)field.clip_y=58;
        field.clip_h=bottom>field.clip_y?bottom-field.clip_y:0;c=&field;
        uint32_t phase=last_tick/35000u;
        for(uint32_t i=0;i<32u;++i){int32_t x=(int32_t)((i*113u+29u)%310u)+5,y=60+(int32_t)((i*71u+phase*(i%3u+1u))%145u);
            box(c,x,y,1,i%4u?1:3,i%4u?0x31acu:0x8cb8u);}
        for(uint32_t i=0;i<12u;++i)if(rock[i].live){int32_t x=rock[i].x,y=rock[i].y,r=rock[i].size;
            /* A tapered tail and shaded stone keep the solid collision body clear. */
            for(int32_t t=1;t<14;++t)box(c,x-r/3,y-r-t,r*2/3+1,1,t<6?0x7188u:0x30e7u);
            arcade_disc(c,x,y,r+1,0x4928u);arcade_disc(c,x,y,r,0xbc0eu);
            arcade_disc(c,x-2,y-2,r>7?r-3:r-2,0xe553u);
            arcade_disc(c,x+r/3,y+r/3,r/3,0x8aacu);box(c,x-r/2,y-r/2,r/2+1,2,0xfedbu);
        }
        bool shield=(int32_t)(last_tick-invulnerable_until)<0;
        if(shield){for(int32_t dy=-21;dy<=21;++dy){int32_t dx=22;while(dx*dx+dy*dy>22*22)--dx;
            box(c,(int32_t)ship-dx,183+dy,2,1,cyan);box(c,(int32_t)ship+dx-1,183+dy,2,1,cyan);}}
        uint32_t flame=5u+(last_tick/70000u)%5u;
        for(int32_t dy=0;dy<(int32_t)flame;++dy)box(c,(int32_t)ship-3+dy/3,192+dy,6-2*(dy/3),1,dy<4?0xffd6u:0xfc88u);
        for(int32_t dy=0;dy<24;++dy){int32_t half=dy<15?dy/4:10-(dy-15)/2;
            box(c,(int32_t)ship-half,168+dy,half*2+1,1,dy<16?0xdf9eu:0x4cb8u);}
        box(c,(int32_t)ship-2,177,5,8,0x2270u);box(c,(int32_t)ship-1,178,2,5,cyan);
        box(c,(int32_t)ship-10,188,4,4,0xfeb2u);box(c,(int32_t)ship+7,188,4,4,0xfeb2u);
        c=full;
        box(c,0,207,320,1,0x294bu);
        if(hit_until&&(int32_t)(last_tick-hit_until)<0){box(c,0,58,3,147,0xfbceu);box(c,317,58,3,147,0xfbceu);}
        if(games_phase==PLAY)arcade_text(c,12,212,"Wheel / </>: steer    Select: shield",white,true);
    }else{
        static const uint16_t colors[]={0xfd4bu,0x4edbu,0xff30u,0xbb7fu};
        arcade_text(c,12,36,"ROUND",muted,true);arcade_value(c,57,33,level,white);
        arcade_text(c,93,36,"SCORE",muted,true);arcade_value(c,134,33,score,white);
        const char *status=games_phase==WATCH?(entered==255u?"GET READY":"WATCH"):games_phase==MISTAKE?"TRY AGAIN":games_phase==PLAY?"YOUR TURN":"";
        arcade_text(c,222,36,status,games_phase==MISTAKE?0xfd4bu:cyan,true);
        /* Clockwise numbering follows the click wheel through the four corners. */
        for(uint32_t i=0;i<4u;++i){int32_t x=16+(i==1u||i==2u?150:0),y=59+(i>=2u?67:0);
            bool selected=focus==i&&games_phase==PLAY,lit=flash==i+1u;
            uint16_t color=colors[i];
            arcade_panel(c,x,y+3,138,59,0x0022u);
            arcade_panel(c,x,y,138,59,selected?white:lit?color:0x294du);
            arcade_panel(c,x+2,y+2,134,55,lit?color:0x1129u);
            box(c,x+7,y+9,3,39,color);
            arcade_symbol(c,x+68,y+28,i,lit?0x10a7u:color);
            arcade_value(c,x+17,y+18,i+1u,lit?0x10a7u:muted);
            if(selected){box(c,x+102,y+26,18,2,white);box(c,x+114,y+23,3,8,white);}
        }
        /* One segment per beat: filled segments are accepted input or shown beats. */
        uint32_t done=entered==255u?0u:games_phase==WATCH?entered+(flash?1u:0u):entered;
        int32_t width=level?280/(int32_t)level:280;
        for(uint32_t i=0;i<level;++i)box(c,20+(int32_t)i*width,194,width-2,4,i<done?cyan:0x294du);
        if(games_phase==WATCH||games_phase==MISTAKE||games_phase==PLAY)
            arcade_text(c,16,207,games_phase==WATCH?(entered==255u&&level>1u?"Round complete! A longer pattern next.":"Watch the symbols. Repeat in order."):games_phase==MISTAKE?"One life lost. Watch and try again.":"Wheel / </>: choose    Select: repeat",white,true);
    }
    arcade_text(c,12,227,games_phase==PAUSED?"Play: resume":games_phase==LOST||games_phase==WON?"Select: retry":"Play: pause",muted,true);arcade_text(c,236,227,"Menu: exit",muted,true);
    if(games_phase==PAUSED||games_phase==LOST||games_phase==WON){
        box(c,0,55,320,152,navy);
        arcade_panel(c,22,65,276,133,0x294du);arcade_panel(c,23,66,274,131,0x10e8u);
        box(c,37,78,3,26,games_phase==LOST?0xfd4bu:cyan);
        arcade_text(c,49,81,games_phase==PAUSED?"Paused":games_phase==WON?"All 24 rounds cleared!":game==COMET?"Run complete":"Out of lives",white,false);
        if(games_phase==PAUSED){arcade_text(c,39,113,game==COMET?"Dodge meteors. Shield costs 40%.":"Remember the order of the symbols.",muted,true);
            arcade_text(c,39,131,game==COMET?"Wheel or </> moves your ship.":"Wheel or </> chooses. Select repeats.",muted,true);}
        else{arcade_text(c,39,113,"SCORE",muted,true);arcade_value(c,86,108,score,white);
            arcade_text(c,173,113,"BEST",muted,true);arcade_value(c,212,108,best[game],cyan);
            arcade_text(c,39,133,game==COMET?"Every meteor dodged earns 5 points.":"Each completed round earns points.",muted,true);}
        arcade_panel(c,38,157,244,26,0x236fu);
        arcade_text(c,51,164,games_phase==PAUSED?"Press Play to resume":"Press Select to play again",white,true);
    }
}
