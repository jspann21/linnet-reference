#include "link.h"

static uint16_t read16(const uint8_t *p) {
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t read32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void write16(uint8_t *p, uint16_t value) {
    p[0] = (uint8_t)value;
    p[1] = (uint8_t)(value >> 8);
}

static void write32(uint8_t *p, uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(value >> (8u * i));
}

static uint32_t crc32(const uint8_t *p, uint32_t size) {
    uint32_t crc = 0xffffffffu;
    for (uint32_t i = 0; i < size; ++i) {
        crc ^= p[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((0u - (crc & 1u)) & 0xedb88320u);
    }
    return ~crc;
}

static int valid_header(const uint8_t *p) {
    uint16_t flags = read16(p + 6);
    return p[0] == 'L' && p[1] == 'N' && p[2] == 'K' && p[3] == '1' &&
           p[4] == 1 && p[5] == 0 && (flags == 0 || flags == 1 || flags == 3) &&
           read16(p + 10) == 0 && read32(p + 12) != 0 &&
           read32(p + 16) <= LINNET_LINK_MAX_PAYLOAD;
}

void ln_link_parser_init(ln_link_parser *parser) {
    parser->used = 0;
    parser->expected = LINNET_LINK_HEADER_SIZE;
    parser->last_sequence = 0;
}

int ln_link_parser_feed(ln_link_parser *parser, uint8_t byte, ln_link_frame *frame) {
    if (parser->used >= LINNET_LINK_MAX_FRAME) goto invalid;
    parser->bytes[parser->used++] = byte;
    if (parser->used == LINNET_LINK_HEADER_SIZE) {
        if (!valid_header(parser->bytes)) goto invalid;
        parser->expected = LINNET_LINK_HEADER_SIZE + read32(parser->bytes + 16) + 4u;
    }
    if (parser->used < parser->expected) return 0;
    if (crc32(parser->bytes, parser->used - 4u) != read32(parser->bytes + parser->used - 4u))
        goto invalid;
    frame->sequence = read32(parser->bytes + 12);
    if (frame->sequence <= parser->last_sequence) goto invalid;
    parser->last_sequence = frame->sequence;
    frame->command = read16(parser->bytes + 8);
    frame->flags = read16(parser->bytes + 6);
    frame->length = read32(parser->bytes + 16);
    frame->payload = parser->bytes + LINNET_LINK_HEADER_SIZE;
    parser->used = 0;
    parser->expected = LINNET_LINK_HEADER_SIZE;
    return 1;
invalid:
    parser->used = 0;
    parser->expected = LINNET_LINK_HEADER_SIZE;
    return -1;
}

size_t ln_link_encode(const ln_link_frame *frame, uint8_t *output, size_t capacity) {
    if (frame->length > LINNET_LINK_MAX_PAYLOAD || frame->sequence == 0 ||
        (frame->flags != 0 && frame->flags != 1 && frame->flags != 3) ||
        (frame->length != 0 && frame->payload == NULL)) return 0;
    size_t total = LINNET_LINK_HEADER_SIZE + frame->length + 4u;
    if (capacity < total) return 0;
    output[0] = 'L'; output[1] = 'N'; output[2] = 'K'; output[3] = '1';
    output[4] = 1; output[5] = 0;
    write16(output + 6, frame->flags);
    write16(output + 8, frame->command);
    write16(output + 10, 0);
    write32(output + 12, frame->sequence);
    write32(output + 16, frame->length);
    for (uint32_t i = 0; i < frame->length; ++i) output[20u + i] = frame->payload[i];
    write32(output + total - 4u, crc32(output, (uint32_t)total - 4u));
    return total;
}
