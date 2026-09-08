#ifndef LINNET_PHOTOS_PIMG_H
#define LINNET_PHOTOS_PIMG_H
#include <stdint.h>
#include <stdbool.h>
struct ln_pimg_header {uint32_t size,albums,photos,levels,tiles,album_at,photo_at,level_at,tile_at,string_at,string_bytes,metadata_crc,data_at,identity;};
struct ln_pimg_album {uint32_t title,bytes,first,count,parent;};
struct ln_pimg_photo {uint32_t album,title,bytes,source,source_bytes,width,height,first,levels,thumb,thumb_crc,jpeg_bytes,jpeg_crc,orientation;};
struct ln_pimg_level {uint32_t photo,width,height,columns,rows,first,count;};
bool ln_pimg_header(const uint8_t *,uint32_t,struct ln_pimg_header *);
bool ln_pimg_album(const struct ln_pimg_header *,const uint8_t *,uint32_t,struct ln_pimg_album *);
bool ln_pimg_photo(const struct ln_pimg_header *,const uint8_t *,uint32_t,struct ln_pimg_photo *);
bool ln_pimg_level(const struct ln_pimg_header *,const uint8_t *,uint32_t,struct ln_pimg_level *);
bool ln_pimg_tile(const struct ln_pimg_header *,const uint8_t *,uint32_t,uint32_t *,uint32_t *);
bool ln_pimg_text(const uint8_t *,uint32_t,bool);
uint32_t ln_pimg_crc_update(uint32_t,const uint8_t *,uint32_t);
#endif
