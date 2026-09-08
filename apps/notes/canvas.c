#include "ui/runtime/ui.h"
/* Trusted AOT callback: fixed rectangle work, no allocation or MMIO. */
void ln_notes_waveform(const struct ln_ui_canvas_context *c) {
    if(!c||!c->pixels||c->w<=0||c->h<=0)return;
    for(int32_t x=0;x<c->w;++x){
        uint32_t phase=((uint32_t)x+c->frame)%32u;
        uint32_t triangle=phase<16u?phase:31u-phase;
        int32_t px=c->x+x,py=c->y+(int32_t)(triangle*(uint32_t)(c->h-1)/15u);
        if(px>=0&&px<220&&py>=0&&py<176&&px>=c->clip_x&&py>=c->clip_y&&
           px-c->clip_x<c->clip_w&&py-c->clip_y<c->clip_h)
            c->pixels[(uint32_t)py*220u+(uint32_t)px]=c->fg;
    }
}
