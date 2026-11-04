/* The scope and generator monitor for the H7-TOOL's display: a 30 x 20 text screen of the unit's own state and counters, drawn one
 * changed row at a time through the driver's non-blocking blit, so it can sit in the main loop beside acquisition and playback.
 *
 * It reads counters and configuration only, never the sample stream (CLAUDE.md invariant 1 holds for this target). A step of
 * h7mon_poll() is bounded: it formats the rows (a few microseconds), or renders one row into the line buffer, or reads one flag.
 * Rows are redrawn only when their text or colour changed, at most ten times a second. Uses h7ui (fw/ui/h7_ui.h): the display,
 * its shadow copy for capture and the blit must be set up by the caller first. */
#ifndef H7_MON_H
#define H7_MON_H
#include <stdint.h>
#include "h7_ui.h"
#include "h7_font.h"

#define H7MON_COLS 30u                                   /* H7LCD_W / H7_FONT_W */
#define H7MON_ROWS 20u                                   /* H7LCD_H / H7_FONT_H */
#define H7MON_LINE_BYTES (H7LCD_W * H7_FONT_H * 2u)      /* one row of text as RGB565: what the line buffer must hold, in memory DMA2 can read */
#define H7MON_PERIOD_MS 100u                             /* the screen is re-read this often */
#define H7MON_BLIT_LIMIT_MS 50u                          /* a row not out by then is abandoned */

enum { H7MON_TEXT, H7MON_HEAD, H7MON_GOOD, H7MON_WARN, H7MON_BAD, H7MON_DIM };   /* a row's colour class */

typedef struct {
	uint8_t  running, playing, chmask, gain1, gain2, coupling;   /* coupling: bit 0 CH1 DC, bit 1 CH2 DC */
	uint32_t adc_period, dac_period;                             /* timer ticks of the 200 MHz base */
	uint32_t frames, lost, sent, tc_missed, ct_bad, adc_ovr;
	uint32_t play_units, play_consumed, play_underruns, play_short, play_min_occ, play_resumes;
	uint32_t uptime_ms, build;
} h7mon_info_t;

void h7mon_init(uint8_t *linebuf);                       /* linebuf: H7MON_LINE_BYTES, 2-byte aligned */
void h7mon_poll(const h7mon_info_t *info);               /* every main-loop pass */
unsigned h7mon_rows_sent(void);                          /* rows drawn so far */
unsigned h7mon_errors(void);                             /* rows abandoned or refused; after the first refusal the monitor stops drawing */

/* the layout, on its own so a test can read it without a display */
void h7mon_format(const h7mon_info_t *info, char rows[H7MON_ROWS][H7MON_COLS + 1], uint8_t color[H7MON_ROWS]);
#endif
