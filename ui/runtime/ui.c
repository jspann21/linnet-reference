#include "ui/runtime/ui.h"
static uint32_t session_theme=UINT32_MAX,active_theme;
static bool theme_ready;
__attribute__((weak)) uint32_t ln_ui_battery_status(void){return UINT32_MAX;}
__attribute__((weak)) uint32_t ln_ui_clock_seconds(void){return UINT32_MAX;}
__attribute__((weak)) uint32_t ln_ui_playback_status(void){return 0;}
__attribute__((weak)) bool ln_ui_clock_begin(void){return false;}
__attribute__((weak)) bool ln_ui_clock_input(struct ln_ui_state*s,uint32_t kind,int32_t value){(void)s;(void)kind;(void)value;return false;}
__attribute__((weak)) void ln_ui_clock_cancel(void){}
__attribute__((weak)) const char *ln_ui_clock_text(const struct ln_ui_node*n,uint32_t item,const char*fallback){(void)n;(void)item;return fallback;}
static void theme_sync(void);
__attribute__((weak)) uint32_t ln_ui_theme_preference(void){return session_theme;}
__attribute__((weak)) void ln_ui_theme_changed(uint32_t index){session_theme=index;}
__attribute__((weak)) const char *ln_ui_theme_status(void){return "Applied";}
uint32_t ln_ui_theme_index(void){uint32_t index=ln_ui_theme_preference();return index<ln_ui_theme_count?index:ln_ui_default_theme;}
uint16_t ln_ui_color(uint32_t value){return value>=LN_UI_COLOR_TOKEN&&value<LN_UI_COLOR_TOKEN+LN_UI_COLOR_COUNT?ln_ui_themes[active_theme].colors[value-LN_UI_COLOR_TOKEN]:(uint16_t)value;}
static void theme_sync(void){
    uint32_t next=ln_ui_theme_index();if(theme_ready&&next==active_theme)return;
    active_theme=next;ln_ui_scenes=ln_ui_themes[active_theme].scenes;ln_ui_font=*ln_ui_themes[active_theme].font;theme_ready=true;
}
static uint32_t layout(void){return ln_ui_themes[active_theme].layout;}
static uint16_t color(uint32_t role){return ln_ui_color(LN_UI_COLOR_TOKEN+role);}
static bool same(const char*a,const char*b){if(!a||!b)return false;while(*a&&*a==*b){++a;++b;}return *a==*b;}
static bool theme_choices(const struct ln_ui_node*n){return n&&same(n->text,"Theme choices");}
static bool apple_style(void){return (ln_ui_themes[active_theme].flags&(LN_UI_THEME_MONOCHROME|LN_UI_THEME_APPLE_PHOTO))!=0;}
__attribute__((weak)) const char *ln_display_settings_text(const struct ln_ui_node*n,uint32_t item,const char*fallback){(void)n;(void)item;return fallback;}
__attribute__((weak)) uint32_t ln_ui_dynamic_count(const struct ln_ui_node*n,uint32_t fallback){(void)n;return fallback;}
__attribute__((weak)) uint32_t ln_ui_dynamic_value(const struct ln_ui_node*n,uint32_t fallback){(void)n;return fallback;}
__attribute__((weak)) const struct ln_ui_asset *ln_ui_dynamic_asset(const struct ln_ui_node*n,const struct ln_ui_asset*fallback){(void)n;return fallback;}
__attribute__((weak)) const struct ln_ui_asset *ln_ui_dynamic_item_asset(const struct ln_ui_node*n,uint32_t item,const struct ln_ui_asset*fallback){(void)n;(void)item;return fallback;}
__attribute__((weak)) const char *ln_ui_dynamic_text(const struct ln_ui_node*n,uint32_t item,const char*fallback){(void)n;(void)item;return fallback;}
struct rect {int32_t x,y,w,h;};
struct painter {uint16_t *pixels;struct rect clip;};
static int32_t min(int32_t a,int32_t b){return a<b?a:b;}
static int32_t max(int32_t a,int32_t b){return a>b?a:b;}
static struct rect intersect(struct rect a,struct rect b){int32_t x=max(a.x,b.x),y=max(a.y,b.y),r=min(a.x+a.w,b.x+b.w),d=min(a.y+a.h,b.y+b.h);return(struct rect){x,y,max(0,r-x),max(0,d-y)};}
static struct rect bounds(const struct ln_ui_node*n){return(struct rect){n->x,n->y,n->w,n->h};}
static const struct rect screen={0,0,220,176};
/* Bounded shift/subtract quotient; ARM7 has no hardware divide. Small layout
 * operands avoid walking all 32 bits, with no compiler division runtime. */
static uint32_t divide(uint32_t numerator,uint32_t denominator){
    if(!denominator||numerator<denominator)return 0;if(denominator==1u)return numerator;
    uint32_t quotient=0,bit=1u;
    while(denominator<=(numerator>>1)){denominator<<=1;bit<<=1;}
    do{if(numerator>=denominator){numerator-=denominator;quotient|=bit;}denominator>>=1;bit>>=1;}while(bit);
    return quotient;
}
/* Every mix caller supplies alpha 0..255. RGB565's largest rounded channel
 * numerator is 63*255+127=16192; this shift/add quotient is exact on that range. */
static uint32_t blend_div255(uint32_t value){return (value+1u+(value>>8))>>8;}
static uint16_t mix(uint16_t a,uint16_t b,uint32_t alpha){uint32_t z=255u-alpha;return(uint16_t)((blend_div255((a>>11)*alpha+(b>>11)*z+127u)<<11)|(blend_div255(((a>>5)&63u)*alpha+((b>>5)&63u)*z+127u)<<5)|blend_div255((a&31u)*alpha+(b&31u)*z+127u));}
typedef uint32_t ln_fill_word __attribute__((may_alias));
static void fill(struct painter*p,struct rect r,uint16_t c){r=intersect(r,p->clip);if(r.w<=0||r.h<=0)return;for(int32_t y=r.y;y<r.y+r.h;++y){uint16_t *dest=p->pixels+(uint32_t)y*220u+(uint32_t)r.x;int32_t left=r.w;uint32_t word=(uint32_t)c|((uint32_t)c<<16);if(left>0&&((uintptr_t)dest&3u)){*dest++=c;--left;}while(left>=2){*(ln_fill_word*)dest=word;dest+=2;left-=2;}if(left>0)*dest=c;}}
static void border(struct painter*p,struct rect r,uint16_t c){fill(p,(struct rect){r.x,r.y,r.w,1},c);fill(p,(struct rect){r.x,r.y+r.h-1,r.w,1},c);fill(p,(struct rect){r.x,r.y,1,r.h},c);fill(p,(struct rect){r.x+r.w-1,r.y,1,r.h},c);}
static uint32_t advance(uint32_t ch){
    if(ch<ln_ui_font.first||ch-ln_ui_font.first>=ln_ui_font.count)ch='?';
    return ln_ui_font.advances&&ch>=ln_ui_font.first&&ch-ln_ui_font.first<ln_ui_font.count?ln_ui_font.advances[ch-ln_ui_font.first]:ln_ui_font.advance;
}
static int32_t text_width(const char*s){int32_t w=0;if(s)for(uint32_t i=0;i<256u&&s[i]&&s[i]!='\n';++i)w+=(int32_t)advance((uint8_t)s[i]);return w;}
static void text_scaled(struct painter*p,int32_t x,int32_t y,const char*s,uint16_t c,uint32_t scale){
    if(!s||!ln_ui_font.alpha||!ln_ui_font.advance||!ln_ui_font.width||!ln_ui_font.height)return;
    int32_t start=x;uint32_t limit=0;
    while(*s&&limit++<1024u){uint32_t ch=(uint8_t)*s++;if(ch=='\n'){x=start;y+=((int32_t)ln_ui_font.height+2)*(int32_t)scale;continue;}
        if(ch<ln_ui_font.first||ch-ln_ui_font.first>=ln_ui_font.count)ch='?';
        if(ch>=ln_ui_font.first&&ch-ln_ui_font.first<ln_ui_font.count){
            uint32_t glyph=ch-ln_ui_font.first,w=ln_ui_font.width,h=ln_ui_font.height,offset=glyph*w*h;
            int32_t gx=x,gy=y;
            if(ln_ui_font.glyphs){const struct ln_ui_glyph*g=&ln_ui_font.glyphs[glyph];gx+=(int32_t)(g->x*scale);gy+=(int32_t)(g->y*scale);w=g->w;h=g->h;offset=g->offset;}
            const uint8_t*a=ln_ui_font.alpha+offset;
            struct rect r=intersect((struct rect){gx,gy,(int32_t)(w*scale),(int32_t)(h*scale)},p->clip);
            for(int32_t yy=r.y;yy<r.y+r.h;++yy)for(int32_t xx=r.x;xx<r.x+r.w;++xx){uint32_t pos=(uint32_t)yy*220u+(uint32_t)xx;uint32_t alpha=a[((uint32_t)(yy-gy)>>(scale-1u))*w+((uint32_t)(xx-gx)>>(scale-1u))];if(ln_ui_themes[active_theme].flags&LN_UI_THEME_MONOCHROME)alpha=alpha>=128u?255u:0u;if(alpha)p->pixels[pos]=alpha==255u?c:mix(c,p->pixels[pos],alpha);}
        }
        x+=(int32_t)(advance(ch)*scale);
    }
}
static void text(struct painter*p,int32_t x,int32_t y,const char*s,uint16_t c){text_scaled(p,x,y,s,c,1u);}
static void fitted_text(struct painter*p,int32_t x,int32_t y,const char*s,uint16_t fg,int32_t width){
    if(!s||width<=0)return;
    if(text_width(s)<=width){text(p,x,y,s,fg);return;}
    char clipped[128];uint32_t length=0;int32_t used=0,ellipsis=text_width("...");
    while(length<124u&&s[length]&&used+(int32_t)advance((uint8_t)s[length])+ellipsis<=width){clipped[length]=s[length];used+=(int32_t)advance((uint8_t)s[length]);++length;}
    if(ellipsis<=width){clipped[length++]='.';clipped[length++]='.';clipped[length++]='.';}clipped[length]=0;text(p,x,y,clipped,fg);
}
static void text_block(struct painter*p,const struct ln_ui_node*n,const char*s,uint16_t fg){
    if(!s)return;
    if(!(n->flags&32u)){
        int32_t w=text_width(s),x=n->x;
        if(n->flags&8u)x+=max(0,(n->w-w)/2);else if(n->flags&16u)x+=max(0,n->w-w);
        int32_t available=n->x+n->w-x;
        if(available>0){if(w<=available)text(p,x,n->y,s,fg);else fitted_text(p,x,n->y,s,fg,available);}return;
    }
    uint32_t at=0;int32_t y=n->y;
    while(s[at]&&at<512u&&y+(int32_t)ln_ui_font.height<=n->y+n->h){
        if(y+2*(int32_t)ln_ui_font.height>n->y+n->h){fitted_text(p,n->x,y,s+at,fg,n->w);break;}
        char line[128];uint32_t len=0,last_space=0;int32_t width=0;
        while(s[at+len]&&s[at+len]!='\n'&&len<127u&&width+(int32_t)advance((uint8_t)s[at+len])<=n->w){
            line[len]=s[at+len];if(line[len]==' ')last_space=len+1;width+=(int32_t)advance((uint8_t)line[len]);++len;
        }
        if(s[at+len]&&s[at+len]!='\n'&&last_space)len=last_space;
        if(!len)break;line[len]=0;text(p,n->x,y,line,fg);at+=len;while(s[at]==' '||s[at]=='\n')++at;y+=(int32_t)ln_ui_font.height;
    }
}
static void gradient(struct painter*p,struct rect r,uint16_t top,uint16_t bottom){
    if((uint32_t)r.x<=220u&&(uint32_t)r.y<=176u&&(uint32_t)r.w<=220u&&(uint32_t)r.h<=176u){struct rect v=intersect(r,p->clip);if(v.w<=0||v.h<=0)return;}
    if(r.h<=0)return;uint32_t denominator=(uint32_t)max(1,r.h-1),step=divide(255u,denominator),remainder=255u-step*denominator,alpha=0,error=0;
    for(int32_t y=0;y<r.h;++y){fill(p,(struct rect){r.x,r.y+y,r.w,1},mix(bottom,top,alpha));alpha+=step;error+=remainder;if(error>=denominator){error-=denominator;++alpha;}}
}
static uint32_t fraction(uint32_t value,uint32_t scale,uint32_t denominator){
    if(!denominator)return 0;uint32_t result=0,remainder=0;
    for(uint32_t i=0;i<scale;++i){if(remainder>=denominator-value){remainder-=denominator-value;++result;}else remainder+=value;}return result;
}
static void number(char out[11],uint32_t n){char rev[10];uint32_t len=0;do{rev[len++]=(char)('0'+n%10u);n/=10u;}while(n&&len<10u);for(uint32_t i=0;i<len;++i)out[i]=rev[len-i-1u];out[len]=0;}
static uint32_t total(const struct ln_ui_node*n){return theme_choices(n)?ln_ui_theme_count:ln_ui_dynamic_count(n,n->count?n->count:n->item_count);}
static bool baked_geometry(const struct ln_ui_node*n){
    uint32_t f=n->flags;
    return n->kind>=LN_UI_VIRTUAL_LIST&&n->kind<=LN_UI_GRID&&
        (f&(LN_UI_GEOMETRY|LN_UI_GEOMETRY_RESERVED))==LN_UI_GEOMETRY&&
        ((f>>LN_UI_GEOMETRY_ROW_SHIFT)&127u)&&((f>>LN_UI_GEOMETRY_COLUMNS_SHIFT)&7u)&&
        ((f>>LN_UI_GEOMETRY_ROWS_SHIFT)&15u)&&((f>>LN_UI_GEOMETRY_WIDTH_SHIFT)&255u);
}
static uint32_t columns(const struct ln_ui_node*n){
    if(baked_geometry(n))return(n->flags>>LN_UI_GEOMETRY_COLUMNS_SHIFT)&7u;
    if(n->kind==LN_UI_GRID)return layout()==LN_UI_LAYOUT_IPOD_PHOTO?5u:layout()==LN_UI_LAYOUT_AURORA?2u:3u;
    return layout()==LN_UI_LAYOUT_BLUEPRINT&&n->kind==LN_UI_MENU&&n->h>=90?2u:1u;
}
static uint32_t row_height(const struct ln_ui_node*n){
    if(baked_geometry(n))return(n->flags>>LN_UI_GEOMETRY_ROW_SHIFT)&127u;
    if(same(n->text,"Clock fields"))return layout()==LN_UI_LAYOUT_GRAPHITE?24u:layout()==LN_UI_LAYOUT_IPOD_PHOTO?22u:(uint32_t)max(18,(int32_t)ln_ui_font.height+3);
    if(n->kind==LN_UI_GRID)return layout()==LN_UI_LAYOUT_IPOD_PHOTO?38u:(uint32_t)max(1,n->h/2);
    if(columns(n)==2u)return 46u;
    return ln_ui_themes[active_theme].row_height;
}
static uint32_t rows(const struct ln_ui_node*n){if(baked_geometry(n))return(n->flags>>LN_UI_GEOMETRY_ROWS_SHIFT)&15u;uint32_t h=row_height(n);return n->h>0?max(1,(int32_t)divide((uint32_t)n->h,h)):1u;}
static uint32_t first_row(uint32_t selected,uint32_t capacity){return divide(selected,capacity)*capacity;}
static bool decorative_asset(const struct ln_ui_node*n,const struct ln_ui_asset*a){
    bool decoration=n->kind==LN_UI_ICON||n->kind==LN_UI_IMAGE||n->kind==LN_UI_ALBUM_ART||n->kind==LN_UI_GRID||n->kind==LN_UI_PHOTO_SURFACE||n->kind==LN_UI_VIDEO_SURFACE;
    return decoration&&n->resource<ln_ui_asset_count&&a==&ln_ui_assets[n->resource];
}
static uint16_t asset_pixel(uint16_t value){
    uint32_t light=(((value>>11)&31u)*77u*255u/31u+((value>>5)&63u)*150u*255u/63u+(value&31u)*29u*255u/31u)>>8;
    if(ln_ui_themes[active_theme].flags&LN_UI_THEME_MONOCHROME)light=light>=128u?255u:0u;
    return mix(color(LN_UI_ARTWORK_BG),color(LN_UI_ARTWORK_FG),light);
}
struct sample_axis {uint32_t index,error,step,remainder,denominator;};
static bool sample_axis_begin(struct sample_axis*axis,uint32_t source,uint32_t destination,uint32_t start,uint32_t count){
    /* Bound products/remainders; unsupported metadata keeps legacy arithmetic. */
    if(!source||source>65535u||!destination||destination>65535u||start>=destination||count>destination-start)return false;
    axis->denominator=destination;axis->step=divide(source,destination);
    axis->remainder=source-axis->step*destination;
    uint32_t product=start*source;axis->index=divide(product,destination);
    axis->error=product-axis->index*destination;return true;
}
static uint32_t sample_axis_next(struct sample_axis*axis){
    uint32_t index=axis->index;axis->index+=axis->step;axis->error+=axis->remainder;
    if(axis->error>=axis->denominator){axis->error-=axis->denominator;++axis->index;}return index;
}
typedef uint32_t ln_image_word __attribute__((may_alias));
static void image_asset(struct painter*p,const struct ln_ui_node*n,const struct ln_ui_asset*a){
    if(!a)return;
    if(!a->pixels||!a->width||!a->height||n->w<=0||n->h<=0)return;
    struct ln_ui_node fitted;
    if(n->kind==LN_UI_ALBUM_ART||n->kind==LN_UI_PHOTO_SURFACE||n->kind==LN_UI_VIDEO_SURFACE){
        fitted=*n;
        if(a->width*(uint32_t)n->h>a->height*(uint32_t)n->w){fitted.h=(int32_t)divide(a->height*(uint32_t)n->w,a->width);fitted.y+=(n->h-fitted.h)/2;}
        else{fitted.w=(int32_t)divide(a->width*(uint32_t)n->h,a->height);fitted.x+=(n->w-fitted.w)/2;}
        if(fitted.w<=0||fitted.h<=0)return;n=&fitted;
    }
    struct rect r=intersect(bounds(n),p->clip);uint32_t source_x[220];bool decoration=decorative_asset(n,a);
    if(!r.w||!r.h)return;
    if(a->width==(uint32_t)n->w&&a->height==(uint32_t)n->h){
        bool paired=!decoration&&a->width<=220u&&a->height<=176u;
        if(paired){uintptr_t source=(uintptr_t)a->pixels,target=(uintptr_t)p->pixels;
            uint32_t bytes=a->width*a->height*2u;
            /* Overlapping storage retains the original forward pixel order. */
            paired=source<target?target-source>=bytes:source-target>=220u*176u*2u;
        }
        for(int32_t y=r.y;y<r.y+r.h;++y){
            const uint16_t *source=a->pixels+(uint32_t)(y-n->y)*a->width+(uint32_t)(r.x-n->x);
            uint16_t *dest=p->pixels+(uint32_t)y*220u+(uint32_t)r.x;
            if(paired&&!(((uintptr_t)source^(uintptr_t)dest)&3u)){
                int32_t left=r.w;
                if((uintptr_t)dest&3u){*dest++=*source++;--left;}
                while(left>=2){*(ln_image_word*)dest=*(const ln_image_word*)source;dest+=2;source+=2;left-=2;}
                if(left>0)*dest=*source;
                continue;
            }
            if(decoration){for(int32_t x=0;x<r.w;++x)dest[x]=asset_pixel(source[x]);}
            else{for(int32_t x=0;x<r.w;++x)dest[x]=source[x];}
        }return;
    }
    struct sample_axis axis;bool fast=sample_axis_begin(&axis,a->width,(uint32_t)n->w,(uint32_t)r.x-(uint32_t)n->x,(uint32_t)r.w);
    for(int32_t x=r.x;x<r.x+r.w;++x)source_x[x-r.x]=fast?sample_axis_next(&axis):divide((uint32_t)(x-n->x)*a->width,(uint32_t)n->w);
    fast=sample_axis_begin(&axis,a->height,(uint32_t)n->h,(uint32_t)r.y-(uint32_t)n->y,(uint32_t)r.h);
    for(int32_t y=r.y;y<r.y+r.h;++y){uint32_t sy=fast?sample_axis_next(&axis):divide((uint32_t)(y-n->y)*a->height,(uint32_t)n->h);
        for(int32_t x=r.x;x<r.x+r.w;++x){uint16_t value=a->pixels[sy*a->width+source_x[x-r.x]];p->pixels[(uint32_t)y*220u+(uint32_t)x]=decoration?asset_pixel(value):value;}
    }
}
static void image(struct painter*p,const struct ln_ui_node*n){image_asset(p,n,ln_ui_dynamic_asset(n,n->resource<ln_ui_asset_count?&ln_ui_assets[n->resource]:0));}
static bool video_covers(const struct painter*p,const struct ln_ui_node*n,const struct ln_ui_asset*a){
    if(!a||!a->pixels||n->w<=0||n->w>220||n->h<=0||n->h>176||
       !a->width||a->width>220u||!a->height||a->height>176u||
       a->width*(uint32_t)n->h!=a->height*(uint32_t)n->w)return false;
    /* Equal bounded aspect ratios make image_asset cover the whole node.
     * Preserve background writes if source storage aliases the framebuffer. */
    uintptr_t source=(uintptr_t)a->pixels,target=(uintptr_t)p->pixels;
    uint32_t bytes=a->width*a->height*2u;
    return source<target?target-source>=bytes:source-target>=220u*176u*2u;
}
static void symbol(struct painter*p,int32_t x,int32_t y,uint32_t kind,uint16_t ink){
    if(kind==1u){for(int32_t yy=0;yy<10;++yy){int32_t inset=yy<5?yy:9-yy;fill(p,(struct rect){x,y+yy,inset+2,1},ink);}}
    else if(kind==2u){fill(p,(struct rect){x,y,3,10},ink);fill(p,(struct rect){x+6,y,3,10},ink);}
    else if(kind==3u){fill(p,(struct rect){x+2,y,7,2},ink);fill(p,(struct rect){x,y+2,2,7},ink);fill(p,(struct rect){x+9,y+2,2,7},ink);fill(p,(struct rect){x,y+6,4,5},ink);fill(p,(struct rect){x+7,y+6,4,5},ink);}
    else if(kind==4u){border(p,(struct rect){x+2,y,7,7},ink);fill(p,(struct rect){x,y+5,11,7},ink);fill(p,(struct rect){x+5,y+7,1,3},color(LN_UI_STATUS_BG));}
    else if(kind==5u){border(p,(struct rect){x,y,11,11},ink);fill(p,(struct rect){x+5,y+2,1,4},ink);fill(p,(struct rect){x+5,y+5,4,1},ink);}
}
static void time_label(char out[6]){
    uint32_t value=ln_ui_clock_seconds();if(value>=86400u){out[0]='-';out[1]='-';out[2]=':';out[3]='-';out[4]='-';out[5]=0;return;}
    uint32_t hour=value/3600u,minute=(value-hour*3600u)/60u;
    out[0]=(char)('0'+hour/10u);out[1]=(char)('0'+hour%10u);out[2]=':';out[3]=(char)('0'+minute/10u);out[4]=(char)('0'+minute%10u);out[5]=0;
}
static void battery(struct painter*p,int32_t x,int32_t y,uint16_t ink){
    uint32_t status=ln_ui_battery_status();border(p,(struct rect){x,y,23,11},ink);fill(p,(struct rect){x+23,y+3,2,5},ink);
    fill(p,(struct rect){x+1,y+1,21,9},color(LN_UI_STATUS_BG));
    if(status!=UINT32_MAX&&(status&255u)<=100u){
        uint32_t width=(status&255u)*19u/100u;struct rect charge={x+2,y+2,(int32_t)width,7};
        gradient(p,charge,mix(color(LN_UI_BATTERY),color(LN_UI_BACKGROUND),130),color(LN_UI_BATTERY));
        if(status&256u){fill(p,(struct rect){x+12,y+1,2,3},ink);fill(p,(struct rect){x+9,y+4,5,2},ink);fill(p,(struct rect){x+9,y+6,2,4},ink);}
        else if(status&512u){fill(p,(struct rect){x+9,y+2,1,2},ink);fill(p,(struct rect){x+13,y+2,1,2},ink);fill(p,(struct rect){x+9,y+4,5,3},ink);fill(p,(struct rect){x+11,y+7,1,2},ink);}
    }else {fill(p,(struct rect){x+7,y+5,9,1},ink);}
}
static void chrome(struct painter*p,struct ln_ui_state*s){
    uint16_t ink=color(LN_UI_MUTED);char clock[6];time_label(clock);
    if(layout()==LN_UI_LAYOUT_AURORA){
        fill(p,(struct rect){0,0,42,176},color(LN_UI_PANEL));fill(p,(struct rect){41,0,1,176},color(LN_UI_BORDER));
        battery(p,8,12,ink);symbol(p,16,43,ln_ui_playback_status(),ink);
        if(s->headphones)symbol(p,15,77,3,ink);if(s->hold)symbol(p,15,109,4,ink);
        symbol(p,16,133,5,ink);fitted_text(p,3,151,clock,ink,37);
    }else if(layout()==LN_UI_LAYOUT_GRAPHITE||layout()==LN_UI_LAYOUT_SUNSET){
        fill(p,(struct rect){0,154,220,22},color(LN_UI_PANEL));
        symbol(p,10,159,ln_ui_playback_status(),ink);if(s->headphones)symbol(p,29,159,3,ink);if(s->hold)symbol(p,48,159,4,ink);
        symbol(p,155,159,5,ink);fitted_text(p,170,156,clock,ink,48);
    }
}
static uint32_t status_signature(void){
    uint32_t seconds=ln_ui_clock_seconds(),minutes=seconds<86400u?seconds/60u:2047u;
    return (ln_ui_battery_status()&1023u)|(minutes<<10)|((ln_ui_playback_status()&3u)<<21);
}
bool ln_ui_status_refresh(struct ln_ui_state*s){
    if(!s)return false;theme_sync();if(s->drawn_status==status_signature())return false;s->dirty|=4u;return true;
}
static void draw_node(struct painter*p,const struct ln_ui_node*n,struct ln_ui_state*s,bool focused){
    if(n->flags&2u)return;
    struct rect previous=p->clip;p->clip=intersect(previous,bounds(n));if(!p->clip.w||!p->clip.h){p->clip=previous;return;}
    uint16_t fg=ln_ui_color(n->fg),bg=ln_ui_color(n->bg);int32_t row_h=(int32_t)row_height(n);
    const char *node_text=ln_ui_clock_text(n,UINT32_MAX,ln_display_settings_text(n,UINT32_MAX,ln_ui_dynamic_text(n,UINT32_MAX,n->text)));
    switch(n->kind){
    case LN_UI_SCREEN:fill(p,bounds(n),bg);chrome(p,s);break;
    case LN_UI_VIEW:fill(p,bounds(n),bg);break;
    case LN_UI_TEXT:
        if(same(n->text,"System clock")){char clock[6];time_label(clock);uint32_t scale=n->h>=(int32_t)(2u*ln_ui_font.height)?2u:1u;
            int32_t width=text_width(clock)*(int32_t)scale;text_scaled(p,n->x+max(0,(n->w-width)/2),n->y,clock,fg,scale);}
        else if(same(n->text,"Clock source")){text_block(p,n,ln_ui_clock_text(n,UINT32_MAX,ln_ui_clock_seconds()<86400u?"Device clock":"Clock unavailable"),fg);}
        else if(same(n->text,"Theme status")){
            char status[32];uint32_t at=0;const char *part=ln_ui_theme_status();
            while(*part&&at<29u)status[at++]=*part++;status[at++]=':';status[at++]=' ';part=ln_ui_themes[active_theme].name;
            while(*part&&at<31u)status[at++]=*part++;status[at]=0;fitted_text(p,n->x,n->y,status,fg,n->w);
        }else text_block(p,n,node_text,fg);break;
    case LN_UI_ICON:case LN_UI_IMAGE:image(p,n);break;
    case LN_UI_VIRTUAL_LIST:case LN_UI_MENU:case LN_UI_GRID:{
        fill(p,bounds(n),bg);uint32_t count=total(n),cols=columns(n);
        uint32_t capacity=rows(n),selected=focused?s->selected:n->index;
        uint32_t first=first_row(divide(selected,cols),capacity)*cols;
        int32_t w=(int32_t)(baked_geometry(n)?(n->flags>>LN_UI_GEOMETRY_WIDTH_SHIFT)&255u:divide((uint32_t)n->w,cols));
        uint32_t column=0,row=0;
        for(uint32_t i=first;i<count&&i-first<capacity*cols;++i){
            struct rect r={n->x+(int32_t)column*w,n->y+(int32_t)row*row_h,w,row_h};
            if(++column==cols){column=0;++row;}
            struct rect visible=intersect(p->clip,r);if(!visible.w||!visible.h)continue;
            bool chosen=focused&&i==s->selected;uint16_t ink=chosen?color(LN_UI_SELECTION_FG):fg;
            struct rect card=r;
            if(layout()==LN_UI_LAYOUT_GRAPHITE){card.y+=2;card.h-=4;}
            if(layout()==LN_UI_LAYOUT_BLUEPRINT&&cols==2u){card.x+=2;card.y+=2;card.w-=4;card.h-=4;}
            if(card.x!=r.x||card.y!=r.y||card.w!=r.w||card.h!=r.h)fill(p,r,bg);
            fill(p,card,chosen?color(LN_UI_SELECTION_BG):layout()==LN_UI_LAYOUT_GRAPHITE?color(LN_UI_PANEL):bg);
            if(layout()==LN_UI_LAYOUT_GRAPHITE||layout()==LN_UI_LAYOUT_BLUEPRINT)border(p,card,chosen?color(LN_UI_ACCENT):color(LN_UI_BORDER));
            if(layout()==LN_UI_LAYOUT_AURORA)fill(p,(struct rect){r.x,r.y,2,r.h},chosen?color(LN_UI_ACCENT):color(LN_UI_PANEL));
            if(layout()==LN_UI_LAYOUT_SUNSET)fill(p,(struct rect){r.x,r.y+r.h-1,r.w,1},color(LN_UI_BORDER));
            if(chosen&&(ln_ui_themes[active_theme].flags&LN_UI_THEME_APPLE_PHOTO))gradient(p,r,mix(color(LN_UI_SELECTION_BG),color(LN_UI_BACKGROUND),210),color(LN_UI_SELECTION_BG));
            struct rect saved=p->clip;p->clip=intersect(saved,r);char num[11],fallback_label[144];const char*label=0;
            if(n->items&&i<n->item_count)label=n->items[i];label=theme_choices(n)?ln_ui_themes[i].name:ln_ui_clock_text(n,i,ln_display_settings_text(n,i,ln_ui_dynamic_text(n,i,label)));if(!label){number(num,i+1u);label=num;
                if(node_text&&n->kind!=LN_UI_GRID){uint32_t len=0;while(len<128u&&node_text[len]){fallback_label[len]=node_text[len];++len;}
                    fallback_label[len++]=' ';for(uint32_t digit=0;num[digit]&&len<143u;++digit)fallback_label[len++]=num[digit];fallback_label[len]=0;label=fallback_label;}
            }
            if(n->kind==LN_UI_GRID){
                const struct ln_ui_asset*a=ln_ui_dynamic_item_asset(n,i,n->resource<ln_ui_asset_count?&ln_ui_assets[n->resource]:0);
                struct ln_ui_node thumbnail=*n;int32_t size=layout()==LN_UI_LAYOUT_IPOD_PHOTO?34:min(56,min(w-8,row_h-(int32_t)ln_ui_font.height-8));
                thumbnail.x=r.x+(w-size)/2;thumbnail.y=r.y+3;thumbnail.w=size;thumbnail.h=size;
                image_asset(p,&thumbnail,a);if(layout()!=LN_UI_LAYOUT_IPOD_PHOTO)fitted_text(p,r.x+3,r.y+size+5,label,ink,r.w-6);
            }else {
                bool mark=theme_choices(n)&&i==active_theme;
                bool arrow=apple_style()&&n->targets&&i<n->item_count&&n->targets[i]<ln_ui_scene_count;
                int32_t padding=(int32_t)ln_ui_themes[active_theme].padding;
                if(layout()==LN_UI_LAYOUT_SUNSET){char ordinal[11];number(ordinal,i+1u);text(p,r.x+2,r.y+max(0,(row_h-(int32_t)ln_ui_font.height)/2),ordinal,ink);padding=max(28,text_width(ordinal)+10);}
                if(cols==2u){struct ln_ui_node tile=*n;tile.x=r.x+7;tile.y=r.y+7;tile.w=r.w-14;tile.h=r.h-12;tile.flags=32u;text_block(p,&tile,label,ink);}
                else fitted_text(p,r.x+padding,r.y+max(0,(row_h-(int32_t)ln_ui_font.height)/2),label,ink,r.w-padding-6-(mark||arrow?12:0));
                if(mark)text(p,r.x+r.w-13,r.y+max(0,(row_h-(int32_t)ln_ui_font.height)/2),"*",ink);
                else if(arrow){int32_t cx=r.x+r.w-13,cy=r.y+row_h/2;for(int32_t d=-3;d<=3;++d)fill(p,(struct rect){cx+3-(d<0?-d:d),cy+d,2,1},ink);}
            }
            p->clip=saved;++s->visible_items;
        }break;}
    case LN_UI_SCROLLBAR:{
        fill(p,bounds(n),bg);uint32_t count=theme_choices(n)?ln_ui_theme_count:ln_ui_dynamic_count(n,n->count?n->count:1u),capacity=1u;
        const struct ln_ui_scene*c=&ln_ui_scenes[s->scene];
        if(c->focus_node<c->count){const struct ln_ui_node*f=&c->nodes[c->focus_node];capacity=rows(f)*columns(f);}
        if(count<=capacity)break;
        uint32_t first=first_row(s->selected,capacity)*capacity;
        int32_t height=max(4,(int32_t)fraction(capacity,(uint32_t)n->h,count));
        int32_t top=min(n->h-height,(int32_t)fraction(first<count?first:count-1u,(uint32_t)n->h,count));
        fill(p,(struct rect){n->x,n->y+top,n->w,height},fg);break;}

    case LN_UI_PROGRESS_BAR:{uint32_t count=ln_ui_dynamic_count(n,n->count?n->count:100u),value=ln_ui_dynamic_value(n,n->index);fill(p,bounds(n),bg);border(p,bounds(n),fg);fill(p,(struct rect){n->x+2,n->y+2,(int32_t)fraction(value>count?count:value,(uint32_t)max(0,n->w-4),count),max(0,n->h-4)},fg);break;}
    case LN_UI_STATUS_BAR:{
        fg=color(LN_UI_STATUS_FG);bg=color(LN_UI_STATUS_BG);
        if(layout()==LN_UI_LAYOUT_IPOD_PHOTO)gradient(p,bounds(n),color(LN_UI_BACKGROUND),bg);else fill(p,bounds(n),bg);
        fill(p,(struct rect){n->x,n->y+n->h-1,n->w,1},color(LN_UI_BORDER));
        int32_t left=n->x+5,right=n->x+n->w-5;
        if(layout()!=LN_UI_LAYOUT_AURORA){
            battery(p,right-25,n->y+5,fg);right-=31;
            if(layout()==LN_UI_LAYOUT_IPOD_PHOTO){
                uint32_t play=ln_ui_playback_status();if(play){symbol(p,left,n->y+5,play,fg);left+=13;}
                if(s->headphones){symbol(p,left,n->y+5,3,fg);left+=13;}if(s->hold){symbol(p,left,n->y+5,4,fg);left+=13;}
            }else if(layout()==LN_UI_LAYOUT_BLUEPRINT){char clock[6];time_label(clock);symbol(p,left,n->y+5,5,fg);fitted_text(p,left+15,n->y+2,clock,fg,42);left+=61;
                if(s->headphones){symbol(p,left,n->y+5,3,fg);left+=14;}if(s->hold){symbol(p,left,n->y+5,4,fg);left+=14;}}
            else if(layout()==LN_UI_LAYOUT_DEFAULT){if(s->headphones){symbol(p,left,n->y+5,3,fg);left+=14;}if(s->hold){symbol(p,left,n->y+5,4,fg);left+=14;}}
            if(layout()==LN_UI_LAYOUT_DEFAULT||layout()==LN_UI_LAYOUT_BLUEPRINT){uint32_t play=ln_ui_playback_status();if(play){symbol(p,left,n->y+5,play,fg);left+=14;}}
        }
        const char *title=node_text?node_text:ln_ui_scenes[s->scene].title;
        int32_t x=left;
        if(layout()==LN_UI_LAYOUT_IPOD_PHOTO)x=max(left,n->x+(n->w-text_width(title))/2);
        fitted_text(p,x,n->y+max(0,(n->h-(int32_t)ln_ui_font.height)/2),title,fg,right-x);
        break;}
    case LN_UI_DIALOG:case LN_UI_TOAST:fill(p,bounds(n),bg);border(p,bounds(n),fg);fitted_text(p,n->x+7,n->y+max(0,(n->h-(int32_t)ln_ui_font.height)/2),node_text,fg,n->w-14);break;
    case LN_UI_ALBUM_ART:case LN_UI_PHOTO_SURFACE:case LN_UI_VIDEO_SURFACE:{
        /* Asset providers are side-effect-free retained-memory lookups. Moving
         * these writes is not a contract for framebuffer-inspecting overrides. */
        bool video=n->kind==LN_UI_VIDEO_SURFACE;
        const struct ln_ui_asset*a=video?ln_ui_dynamic_asset(n,n->resource<ln_ui_asset_count?&ln_ui_assets[n->resource]:0):0;
        if(!video||!video_covers(p,n,a)){fill(p,bounds(n),bg);border(p,bounds(n),color(LN_UI_BORDER));}
        if(video)image_asset(p,n,a);else image(p,n);
        text(p,n->x+7,n->y+7,node_text?node_text:"Preview",fg);break;}
    case LN_UI_CANVAS_SURFACE:{
        fill(p,bounds(n),bg);
        if(n->canvas){const struct ln_ui_canvas_context context={p->pixels,n->x,n->y,n->w,n->h,p->clip.x,p->clip.y,p->clip.w,p->clip.h,s->animation,fg,bg};n->canvas(&context);}
        else {border(p,bounds(n),fg);text(p,n->x+7,n->y+7,node_text,fg);}
        break;}
    default:break;
    }if(n->flags&4u)border(p,bounds(n),fg);p->clip=previous;
}
static const struct ln_ui_scene*scene(const struct ln_ui_state*s){return s->scene<ln_ui_scene_count&&s->scene<32u?&ln_ui_scenes[s->scene]:0;}
static const struct ln_ui_node*focus(const struct ln_ui_state*s){const struct ln_ui_scene*c=scene(s);return c&&c->focus_node<c->count?&c->nodes[c->focus_node]:0;}
uint32_t ln_ui_visible_capacity(const struct ln_ui_state*s){
    theme_sync();const struct ln_ui_node*n=focus(s);if(!n||(n->kind!=LN_UI_MENU&&n->kind!=LN_UI_VIRTUAL_LIST&&n->kind!=LN_UI_GRID))return 0;
    return rows(n)*columns(n);
}
uint32_t ln_ui_focused_count(const struct ln_ui_state*s){
    theme_sync();const struct ln_ui_node*n=focus(s);return n&&(n->kind==LN_UI_MENU||n->kind==LN_UI_VIRTUAL_LIST||n->kind==LN_UI_GRID)?total(n):0;
}
static bool change_scene(struct ln_ui_state*s,uint32_t target){if(target>=ln_ui_scene_count||target>=32u||!(ln_ui_enabled_scenes&(1u<<target))||target==s->scene)return false;bool editor=same(ln_ui_scenes[target].id,"linnet.system.clock-edit");if(editor&&!ln_ui_clock_begin()){s->dirty|=1u;return false;}s->selections[s->scene]=s->selected;s->scene=target;s->selected=editor?0u:s->selections[target];const struct ln_ui_node*n=focus(s);uint32_t count=n?total(n):0;if(theme_choices(n))s->selected=ln_ui_theme_index();if(!count)s->selected=0;else if(s->selected>=count)s->selected=count-1u;s->dirty|=1u;++s->transitions;++s->scene_epoch;return true;}
void ln_ui_refresh(struct ln_ui_state*s){if(!s)return;theme_sync();const struct ln_ui_node*n=focus(s);uint32_t count=n?total(n):0;if(!count)s->selected=0;else if(s->selected>=count)s->selected=count-1u;if(s->scene<32u)s->selections[s->scene]=s->selected;s->dirty|=1u;}
void ln_ui_refresh_content(struct ln_ui_state*s){
    if(!s)return;const struct ln_ui_node*n=focus(s);uint32_t count=n?total(n):0;
    if(!count)s->selected=0;else if(s->selected>=count)s->selected=count-1u;
    if(s->scene<32u)s->selections[s->scene]=s->selected;s->dirty|=16u;
}
bool ln_ui_show(struct ln_ui_state*s,const char*id){if(!s||!id)return false;for(uint32_t i=0;i<ln_ui_scene_count&&i<32u;++i){const char*other=ln_ui_scenes[i].id;uint32_t j=0;if(!other)continue;while(j<128u&&id[j]&&id[j]==other[j])++j;if(j<128u&&!id[j]&&!other[j])return change_scene(s,i);}return false;}
void ln_ui_init(struct ln_ui_state*s){if(!s)return;theme_sync();*s=(struct ln_ui_state){.dirty=1u,.action=UINT32_MAX,.scene_epoch=1u};
    for(uint32_t i=0;i<ln_ui_scene_count&&i<32u;++i){const struct ln_ui_scene*c=&ln_ui_scenes[i];if(c->focus_node<c->count){const struct ln_ui_node*n=&c->nodes[c->focus_node];uint32_t count=total(n);s->selections[i]=count?(n->index<count?n->index:count-1u):0;}}s->selected=s->selections[0];
}
bool ln_ui_input(struct ln_ui_state*s,uint32_t kind,int32_t value){if(!s)return false;theme_sync();
    if(kind==3u||kind==4u){bool v=value!=0;bool *old=kind==3u?&s->hold:&s->headphones;if(*old==v)return false;*old=v;s->dirty|=4u;return true;}
    bool clock_edit=same(ln_ui_scenes[s->scene].id,"linnet.system.clock-edit");
    if(clock_edit&&(kind==1u||kind==2u)){
        uint32_t pressed=kind==2u?(uint32_t)value&~s->buttons:0;
        if(!s->hold&&(pressed&1u)){ln_ui_clock_cancel();s->buttons=(uint32_t)value;return ln_ui_show(s,"linnet.system.clock");}
        if(ln_ui_clock_input(s,kind,value)){s->dirty|=1u;return true;}
        if(kind==2u){s->buttons=(uint32_t)value;return false;}
    }
    if(kind==2u&&!s->hold&&same(ln_ui_scenes[s->scene].id,"linnet.system.clock")&&((uint32_t)value&~s->buttons&16u)){
        s->buttons=(uint32_t)value;(void)ln_ui_show(s,"linnet.system.clock-edit");s->dirty|=1u;return true;
    }
    if(kind==2u){uint32_t pressed=(uint32_t)value&~s->buttons;s->buttons=(uint32_t)value;if(s->hold)return false;if(pressed&1u){if(same(ln_ui_scenes[s->scene].id,"linnet.system.themes"))return ln_ui_show(s,"linnet.system.settings");return change_scene(s,0);}if(pressed&4u){for(uint32_t i=s->scene+1u;i<ln_ui_scene_count&&i<32u;++i)if(ln_ui_enabled_scenes&(1u<<i))return change_scene(s,i)||(s->dirty&1u);return false;}if(pressed&8u){for(uint32_t i=s->scene;i;--i)if(ln_ui_enabled_scenes&(1u<<(i-1u)))return change_scene(s,i-1u)||(s->dirty&1u);return false;}if(pressed&16u){const struct ln_ui_node*n=focus(s);if(theme_choices(n)&&s->selected<ln_ui_theme_count){ln_ui_theme_changed(s->selected);theme_sync();s->dirty|=1u;return true;}if(n&&n->targets&&s->selected<n->item_count){uint32_t target=n->targets[s->selected];if(target==LINNET_UI_ACTION_SYNC){s->action=target;return false;}return change_scene(s,target);}}return false;}
    if(kind!=1u||s->hold||!value)return false;const struct ln_ui_node*n=focus(s);uint32_t count=n?total(n):0;if(!count)return false;
    int64_t next=(int64_t)s->selected+value;if(next<0)next=0;if((uint64_t)next>=count)next=count-1u;if((uint32_t)next==s->selected)return false;s->selected=(uint32_t)next;s->selections[s->scene]=s->selected;s->dirty|=2u;return true;
}
static void paint(struct ln_ui_state*s,uint16_t*pixels,struct rect r,ln_ui_damage_fn damage){
    r=intersect(r,screen);if(!r.w||!r.h)return;struct painter p={pixels,r};const struct ln_ui_scene*c=scene(s);
    bool covered=false;
    if(c&&c->nodes&&c->count&&c->count<=1024u){const struct ln_ui_node*n=&c->nodes[0];
        if(n->kind==LN_UI_SCREEN&&!(n->flags&2u)){struct rect cover=intersect(bounds(n),r);covered=cover.x==r.x&&cover.y==r.y&&cover.w==r.w&&cover.h==r.h;}
    }
    if(!covered)fill(&p,r,color(LN_UI_BACKGROUND));
    if(c)for(uint32_t i=0;i<c->count&&i<1024u;++i)draw_node(&p,&c->nodes[i],s,i==c->focus_node);
    s->painted_pixels+=(uint32_t)(r.w*r.h);if(damage)damage(r.x,r.y,r.w,r.h);
}
/* Count the same clipped cells as a full paint without rasterizing their text
 * or media when only the status chrome needs an update. */
static uint32_t visible_cells(const struct ln_ui_state*s,const struct ln_ui_scene*c){
    uint32_t visible=0;
    for(uint32_t j=0;c&&j<c->count&&j<1024u;++j){const struct ln_ui_node*n=&c->nodes[j];
        if((n->flags&2u)||n->kind<LN_UI_VIRTUAL_LIST||n->kind>LN_UI_GRID)continue;
        struct rect clip=intersect(bounds(n),screen);if(!clip.w||!clip.h)continue;
        uint32_t cols=columns(n),capacity=rows(n),count=total(n);
        uint32_t selected=j==c->focus_node?s->selected:n->index;
        uint32_t first=first_row(divide(selected,cols),capacity)*cols;
        int32_t w=(int32_t)(baked_geometry(n)?(n->flags>>LN_UI_GEOMETRY_WIDTH_SHIFT)&255u:divide((uint32_t)n->w,cols)),h=(int32_t)row_height(n);
        uint32_t column=0,row=0;
        for(uint32_t i=first;i<count&&i-first<capacity*cols;++i){
            struct rect cell=intersect((struct rect){n->x+(int32_t)column*w,n->y+(int32_t)row*h,w,h},clip);
            if(cell.w&&cell.h)++visible;if(++column==cols){column=0;++row;}
        }
    }return visible;
}
static bool selection_damage(struct ln_ui_state*s,uint16_t*pixels,const struct ln_ui_node*n,ln_ui_damage_fn damage){
    if(n->kind!=LN_UI_MENU&&n->kind!=LN_UI_VIRTUAL_LIST&&n->kind!=LN_UI_GRID)return false;
    uint32_t cols=columns(n),capacity=rows(n);
    uint32_t old_first=first_row(divide(s->drawn_selected,cols),capacity)*cols;
    uint32_t new_first=first_row(divide(s->selected,cols),capacity)*cols;
    if(old_first!=new_first)return false;
    uint32_t indexes[2]={s->drawn_selected,s->selected};
    int32_t width=(int32_t)divide((uint32_t)n->w,cols),height=(int32_t)row_height(n);
    for(uint32_t i=0;i<2u;++i){uint32_t cell=indexes[i]-new_first,row=divide(cell,cols),column=cell-row*cols;
        struct rect r={n->x+(int32_t)column*width,n->y+(int32_t)row*height,width,height};
        paint(s,pixels,intersect(r,bounds(n)),damage);
    }
    return true;
}
/* A single painter owns the framebuffer. Bind snapshots to state and scene
 * epoch; changing owner/layout safely falls back to a complete repaint. Fixed
 * limits cover the search scene without enlarging the arena/stack shell state. */
#define CONTENT_ROWS 8u
#define CONTENT_NODES 8u
static struct {
    const struct ln_ui_state *owner;uint32_t scene,epoch,first,count,selected;
    bool valid,present[CONTENT_ROWS];char labels[CONTENT_ROWS][256];
    char texts[CONTENT_NODES][256];
} content;
static bool text_same(const char *a,const char *b){
    if(!a||!b)return a==b;
    for(uint32_t i=0;i<256u;++i){if(a[i]!=b[i])return false;if(!a[i])return true;}
    return false;
}
static bool text_save(char out[256],const char *in){
    if(!in)in="";
    for(uint32_t i=0;i<256u;++i){out[i]=in[i];if(!in[i])return true;}
    out[255]=0;return false;
}
static const char *content_text(const struct ln_ui_node *n,uint32_t item){
    const char *fallback=item==UINT32_MAX?n->text:n->items&&item<n->item_count?n->items[item]:0;
    return ln_display_settings_text(n,item,ln_ui_dynamic_text(n,item,fallback));
}
static bool content_layout(const struct ln_ui_state*s){
    const struct ln_ui_scene*c=scene(s);const struct ln_ui_node*n=focus(s);
    if(!c||c->count>CONTENT_NODES||!n||n->kind!=LN_UI_VIRTUAL_LIST||rows(n)>CONTENT_ROWS)return false;
    for(uint32_t i=0;i<c->count;++i){uint32_t kind=c->nodes[i].kind;
        if(kind==LN_UI_VIRTUAL_LIST){if(i!=c->focus_node)return false;}
        else if(kind!=LN_UI_SCREEN&&kind!=LN_UI_VIEW&&kind!=LN_UI_TEXT&&kind!=LN_UI_STATUS_BAR&&kind!=LN_UI_SCROLLBAR)return false;
    }return true;
}
static void content_save(const struct ln_ui_state*s){
    content.valid=false;if(!content_layout(s))return;
    const struct ln_ui_scene*c=scene(s);const struct ln_ui_node*n=focus(s);
    uint32_t capacity=rows(n),first=first_row(s->selected,capacity),count=total(n);
    for(uint32_t i=0;i<capacity;++i){
        content.present[i]=first+i<count;
        const char *label=content.present[i]?content_text(n,first+i):"";
        if((content.present[i]&&!label)||!text_save(content.labels[i],label))return;
    }
    for(uint32_t i=0;i<c->count;++i)
        if(!text_save(content.texts[i],content_text(&c->nodes[i],UINT32_MAX)))return;
    content.owner=s;content.scene=s->scene;content.epoch=s->scene_epoch;
    content.first=first;content.count=count;content.selected=s->selected;content.valid=true;
}
static bool content_damage(struct ln_ui_state*s,uint16_t*pixels,ln_ui_damage_fn damage){
    if(!content.valid||content.owner!=s||content.scene!=s->scene||content.epoch!=s->scene_epoch||!content_layout(s))return false;
    const struct ln_ui_scene*c=scene(s);const struct ln_ui_node*n=focus(s);
    uint32_t capacity=rows(n),first=first_row(s->selected,capacity),count=total(n);
    if(first!=content.first)paint(s,pixels,bounds(n),damage);
    else for(uint32_t i=0;i<capacity;++i){
        bool present=first+i<count;const char *label=present?content_text(n,first+i):"";
        bool chosen=present&&first+i==s->selected,was_chosen=content.present[i]&&first+i==content.selected;
        if(present!=content.present[i]||chosen!=was_chosen||!text_same(label,content.labels[i])){
            struct rect r={n->x,n->y+(int32_t)i*((int32_t)row_height(n)),n->w,(int32_t)row_height(n)};
            paint(s,pixels,intersect(r,bounds(n)),damage);
        }
    }
    for(uint32_t i=0;i<c->count;++i){const struct ln_ui_node*node=&c->nodes[i];
        if((node->kind==LN_UI_SCROLLBAR&&(count!=content.count||s->selected!=content.selected))||
           ((node->kind==LN_UI_TEXT||node->kind==LN_UI_STATUS_BAR)&&
            !text_same(content_text(node,UINT32_MAX),content.texts[i])))paint(s,pixels,bounds(node),damage);
    }
    return true;
}
void ln_ui_render(struct ln_ui_state*s,uint16_t*pixels,ln_ui_damage_fn damage){if(!s||!pixels)return;theme_sync();if(s->drawn_theme!=active_theme){s->dirty|=1u;++s->scene_epoch;}
    (void)ln_ui_status_refresh(s);if(!s->dirty)return;
    if(s->rendered&&!(s->dirty&1u)){if(s->selected==s->drawn_selected)s->dirty&=~2u;if(((s->hold?1u:0u)|(s->headphones?2u:0u))==s->drawn_flags&&status_signature()==s->drawn_status)s->dirty&=~4u;if(!s->dirty)return;}
    uint32_t painted_before=s->painted_pixels;const struct ln_ui_scene*c=scene(s);s->visible_items=0;
    if(!s->rendered||(s->dirty&1u))paint(s,pixels,screen,damage);
    else if(s->dirty==4u&&!same(ln_ui_scenes[s->scene].id,"linnet.system.clock")&&
            (layout()==LN_UI_LAYOUT_AURORA||layout()==LN_UI_LAYOUT_GRAPHITE||layout()==LN_UI_LAYOUT_SUNSET)){
        paint(s,pixels,layout()==LN_UI_LAYOUT_AURORA?(struct rect){0,0,42,176}:(struct rect){0,154,220,22},damage);
        for(uint32_t i=0;c&&i<c->count&&i<1024u;++i){const struct ln_ui_node*n=&c->nodes[i];
            if(n->kind==LN_UI_STATUS_BAR||(n->deps&16u))paint(s,pixels,bounds(n),damage);
        }
        s->visible_items=visible_cells(s,c);
    }
    else if((s->dirty&4u)&&(layout()==LN_UI_LAYOUT_AURORA||layout()==LN_UI_LAYOUT_GRAPHITE||layout()==LN_UI_LAYOUT_SUNSET||same(ln_ui_scenes[s->scene].id,"linnet.system.clock")))paint(s,pixels,screen,damage);
    else {
        if((s->dirty&16u)&&!content_damage(s,pixels,damage))paint(s,pixels,screen,damage);
        if(c)for(uint32_t i=0;i<c->count&&i<1024u;++i){const struct ln_ui_node*n=&c->nodes[i];bool selected=(s->dirty&2u)&&(i==c->focus_node||n->kind==LN_UI_SCROLLBAR||(n->deps&3u));bool status=(s->dirty&4u)&&(n->kind==LN_UI_STATUS_BAR||(n->deps&16u));bool animation=(s->dirty&8u)&&(n->deps&4u);if(selected&&!status&&!animation&&i==c->focus_node&&selection_damage(s,pixels,n,damage))continue;if(selected||status||animation)paint(s,pixels,bounds(n),damage);}
    }
    /* Report visible rows, not the subset repainted by incremental damage. */
    if((s->dirty&16u)&&content_layout(s)){const struct ln_ui_node*n=focus(s);uint32_t count=total(n),capacity=rows(n),first=first_row(s->selected,capacity);s->visible_items=count>first?min((int32_t)(count-first),(int32_t)capacity):0;}
    content_save(s);
    s->drawn_status=status_signature();s->drawn_theme=active_theme;s->drawn_scene=s->scene;s->drawn_selected=s->selected;s->drawn_flags=(s->hold?1u:0u)|(s->headphones?2u:0u);s->dirty=0;s->rendered=true;if(s->painted_pixels!=painted_before)++s->paint_count;
}
void ln_ui_animate(struct ln_ui_state*s,uint16_t*pixels,uint32_t frame,ln_ui_damage_fn damage){if(!s)return;if(s->animation!=frame){s->animation=frame;const struct ln_ui_scene*c=scene(s);if(c)for(uint32_t i=0;i<c->count&&i<1024u;++i)if(c->nodes[i].deps&4u){s->dirty|=8u;break;}}ln_ui_render(s,pixels,damage);}
uint32_t ln_ui_take_action(struct ln_ui_state*s){if(!s)return UINT32_MAX;uint32_t action=s->action;s->action=UINT32_MAX;return action;}
