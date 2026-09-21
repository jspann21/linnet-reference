#ifndef LINNET_CODEC_H
#define LINNET_CODEC_H
#include <stdbool.h>
#include <stdint.h>
typedef bool (*ln_codec_writer)(uint8_t reg,uint16_t value);
bool ln_codec_rate_supported(uint32_t rate);
bool ln_codec_rate(ln_codec_writer write,uint32_t rate);
bool ln_codec_init(ln_codec_writer write,uint32_t rate);
bool ln_codec_volume(ln_codec_writer write,int32_t db_tenths);
bool ln_codec_lineout(ln_codec_writer write,bool enabled);
bool ln_codec_mute(ln_codec_writer write,bool mute);
bool ln_codec_off(ln_codec_writer write);
#endif
