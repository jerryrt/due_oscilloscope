/* An 8 x 16 bitmap font, ASCII 32..126 (tools/gen_font.py). */
#ifndef H7_FONT_INCLUDED
#define H7_FONT_INCLUDED
#include <stdint.h>
#define H7_FONT_W 8u
#define H7_FONT_H 16u
extern const uint8_t h7_font8x16[95][16];
#endif
