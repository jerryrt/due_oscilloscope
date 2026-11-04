/* The scope and generator monitor. See h7_mon.h. */
#include "h7_mon.h"

#ifdef H7MON_PROFILE
#define PROF_NOW() (*(volatile uint32_t *)0xE0001004u)
#define PROF_START(v) uint32_t v = PROF_NOW()
volatile uint32_t h7mon_prof[8];       /* max cycles of one step: 0 render slice, 1 begin, 2 blit_start, 3 format slice, 4 poll+end, 5 shadow slice, 6 copy slice */
#define PROF_MAX(i, t0) do { uint32_t d_ = PROF_NOW() - (t0); if (d_ > h7mon_prof[i]) h7mon_prof[i] = d_; } while (0)
#else
#define PROF_NOW() 0u
#define PROF_START(v) (void)0
#define PROF_MAX(i, t0) do { } while (0)
#endif
static uint8_t *linebuf;
static char shown[H7MON_ROWS][H7MON_COLS + 1], cur[H7MON_ROWS][H7MON_COLS + 1];
static uint8_t shown_color[H7MON_ROWS], cur_color[H7MON_ROWS];
static uint32_t dirty, last_snap, busy_since;
static int busy_row = -1, first = 1, dead;
static unsigned rows_sent, errors;

/* ---- text helpers: integer arithmetic only, bounded ---- */
static unsigned put_str(char *d, unsigned n, const char *s) { unsigned i = 0; while (s[i] && i < n) { d[i] = s[i]; i++; } return i; }
static unsigned put_u32(char *d, uint32_t v)
{
	char t[10]; unsigned n = 0, i;
	do { t[n++] = (char)('0' + v % 10u); v /= 10u; } while (v);
	for (i = 0; i < n; i++) d[i] = t[n - 1 - i];
	return n;
}
/* "left" at the left edge, "right" at the right edge, spaces between, the whole row H7MON_COLS wide and terminated */
static void line(char *row, const char *left, const char *right)
{
	unsigned l = 0, r = 0;
	while (left[l] && l < H7MON_COLS) l++;
	while (right[r] && r < H7MON_COLS) r++;
	if (l + r + 1 > H7MON_COLS) l = r >= H7MON_COLS ? 0u : H7MON_COLS - r - 1u;       /* too long: the left text gives way */
	for (unsigned i = 0; i < H7MON_COLS; i++) row[i] = ' ';
	for (unsigned i = 0; i < l; i++) row[i] = left[i];
	for (unsigned i = 0; i < r; i++) row[H7MON_COLS - r + i] = right[i];
	row[H7MON_COLS] = 0;
}
static void line_u(char *row, const char *left, uint32_t v) { char t[12]; t[put_u32(t, v)] = 0; line(row, left, t); }
static void rate_text(char *out, uint32_t period)               /* a timer period of the 200 MHz base as a sample rate */
{
	if (period == 0) { out[put_str(out, 8, "-")] = 0; return; }
	uint32_t khz = 200000000u / period / 1000u, n;
	if (khz >= 1000u) { n = put_u32(out, khz / 1000u); out[n++] = '.'; out[n++] = (char)('0' + khz / 100u % 10u); out[n++] = (char)('0' + khz / 10u % 10u); out[n++] = (char)('0' + khz % 10u); n += put_str(out + n, 8, " MS/s"); }
	else { n = put_u32(out, khz); n += put_str(out + n, 8, " kS/s"); }
	out[n] = 0;
}
static void gain_text(char *out, uint8_t gain, uint8_t dc)
{
	unsigned n = 0;
	out[n++] = 'g'; out[n++] = (char)('0' + (gain & 7u)); out[n++] = ' ';
	n += put_str(out + n, 3, dc ? "DC" : "AC");
	out[n] = 0;
}

/* One row of the layout. A row is built from the info alone, so the monitor can format a few rows per step. */
static void format_row(const h7mon_info_t *i, unsigned r, char *row, uint8_t *color)
{
	char a[24], b[24];
	line(row, "", ""); *color = H7MON_TEXT;
	switch (r) {
	case 0: line(row, "   H7-TOOL  SCOPE / AWG", ""); *color = H7MON_HEAD; break;
	case 2: line(row, "SCOPE", i->running ? "RUN" : "STOP"); *color = i->running ? H7MON_GOOD : H7MON_DIM; break;
	case 3: line(row, "channels", i->chmask == 3 ? "CH1+CH2" : i->chmask == 1 ? "CH1" : i->chmask == 2 ? "CH2" : "none"); break;
	case 4: rate_text(a, i->adc_period); line(row, "sample rate", a); break;
	case 5: gain_text(a, i->gain1, i->coupling & 1u); line(row, "CH1", a); break;
	case 6: gain_text(a, i->gain2, (i->coupling >> 1) & 1u); line(row, "CH2", a); break;
	case 7: line_u(row, "frames", i->frames); break;
	case 8: line_u(row, "sent", i->sent); break;
	case 9: line_u(row, "lost", i->lost); *color = i->lost ? H7MON_BAD : H7MON_TEXT; break;
	case 10: { unsigned n = put_u32(a, i->tc_missed); a[n++] = '/'; n += put_u32(a + n, i->ct_bad); a[n++] = '/'; n += put_u32(a + n, i->adc_ovr); a[n] = 0;
	           line(row, "missed/bad/ovr", a); *color = (i->tc_missed | i->ct_bad | i->adc_ovr) ? H7MON_WARN : H7MON_TEXT; } break;
	case 12: line(row, "AWG", i->playing ? "PLAY" : "IDLE"); *color = i->playing ? H7MON_GOOD : H7MON_DIM; break;
	case 13: rate_text(a, i->dac_period); line(row, "update rate", a); break;
	case 14: line_u(row, "units queued", i->play_units); break;
	case 15: line_u(row, "consumed", i->play_consumed); break;
	case 16: line_u(row, "underruns", i->play_underruns); *color = i->play_underruns ? H7MON_BAD : H7MON_TEXT; break;
	case 17: { unsigned n = put_u32(a, i->play_min_occ); a[n++] = '/'; n += put_u32(a + n, i->play_resumes); a[n] = 0; line(row, "min occ/resumes", a); } break;
	case 18: line_u(row, "short", i->play_short); *color = i->play_short ? H7MON_WARN : H7MON_TEXT; break;
	case 19: { uint32_t sec = i->uptime_ms / 1000u, h = sec / 3600u, mn = sec / 60u % 60u, sc = sec % 60u; unsigned n = 0;
	           a[n++] = 'u'; a[n++] = 'p'; a[n++] = ' ';
	           if (h > 99u) h = 99u;
	           a[n++] = (char)('0' + h / 10u); a[n++] = (char)('0' + h % 10u); a[n++] = ':'; a[n++] = (char)('0' + mn / 10u); a[n++] = (char)('0' + mn % 10u);
	           a[n++] = ':'; a[n++] = (char)('0' + sc / 10u); a[n++] = (char)('0' + sc % 10u); a[n] = 0;
	           b[0] = 'b'; b[1] = 'u'; b[2] = 'i'; b[3] = 'l'; b[4] = 'd'; b[5] = ' '; b[6 + put_u32(b + 6, i->build)] = 0;
	           line(row, a, b); *color = H7MON_DIM; } break;
	default: break;                                           /* the blank rows */
	}
}

void h7mon_format(const h7mon_info_t *info, char rows[H7MON_ROWS][H7MON_COLS + 1], uint8_t color[H7MON_ROWS])
{
	for (unsigned r = 0; r < H7MON_ROWS; r++) format_row(info, r, rows[r], &color[r]);
}

/* ---- drawing ---- */
static uint16_t fg_of(uint8_t c)
{
	switch (c) { case H7MON_GOOD: return 0x07E0; case H7MON_WARN: return 0xFFE0; case H7MON_BAD: return 0xF800; case H7MON_DIM: return 0x8410; default: return 0xFFFF; }
}

/* A row is drawn in slices, each a few tens of microseconds, because the main loop beside it has a frame to hand over every 0.4 ms at the
 * top sample rate: render glyph rows into rowbuf (fast RAM) two pixels to a store through a four-entry table, copy it by words into the DMA
 * buffer (nothing is read back from it), open the window, start the transfer, copy the shadow, wait for the end. */
static uint8_t rowbuf[H7MON_LINE_BYTES] __attribute__((aligned(4)));
#define RENDER_SLICES 4u                                   /* glyph rows per slice: 16 / 4 */
#define COPY_SLICES   4u
#define SHADOW_SLICES 4u
#define FORMAT_SLICES 4u                                   /* rows per slice: 20 / 4 */

static void render_slice(unsigned r, unsigned slice)
{
	uint8_t c = cur_color[r];
	uint16_t fg = c == H7MON_HEAD ? 0xFFFF : fg_of(c), bg = c == H7MON_HEAD ? 0x0014 : 0x0000;
	uint32_t fgs = (uint16_t)((fg >> 8) | (fg << 8)), bgs = (uint16_t)((bg >> 8) | (bg << 8));      /* big-endian on the wire; first pixel in the low half */
	uint32_t pair[4] = { bgs | bgs << 16, bgs | fgs << 16, fgs | bgs << 16, fgs | fgs << 16 };       /* index: (left pixel set) << 1 | (right pixel set) */
	unsigned y0 = slice * (H7_FONT_H / RENDER_SLICES);
	uint32_t *d = (uint32_t *)(void *)rowbuf + y0 * H7MON_COLS * 4u;
	for (unsigned y = y0; y < y0 + H7_FONT_H / RENDER_SLICES; y++)
		for (unsigned col = 0; col < H7MON_COLS; col++) {
			unsigned ch = (unsigned char)cur[r][col];
			uint8_t g = (ch >= 32u && ch <= 126u) ? h7_font8x16[ch - 32u][y] : h7_font8x16['?' - 32][y];
			*d++ = pair[(g >> 6) & 3u]; *d++ = pair[(g >> 4) & 3u]; *d++ = pair[(g >> 2) & 3u]; *d++ = pair[g & 3u];
		}
}

static void copy_slice(unsigned slice)
{
	enum { WORDS = H7MON_LINE_BYTES / 4u / COPY_SLICES };
	volatile uint32_t *o = (volatile uint32_t *)(void *)linebuf + slice * WORDS; const uint32_t *i = (const uint32_t *)(const void *)rowbuf + slice * WORDS;
	for (unsigned n = 0; n < WORDS; n++) o[n] = i[n];
}

static void copy_row(char *dst, const char *src) { for (unsigned i = 0; i <= H7MON_COLS; i++) dst[i] = src[i]; }

enum { P_IDLE, P_FORMAT, P_RENDER, P_COPY, P_BEGIN, P_START, P_SHADOW, P_WAIT };
static int phase = P_IDLE;
static unsigned slice, row;
static h7mon_info_t snap;

void h7mon_init(uint8_t *buf) { linebuf = buf; dirty = 0; busy_row = -1; first = 1; dead = 0; rows_sent = errors = 0; phase = P_IDLE; slice = 0; }
unsigned h7mon_rows_sent(void) { return rows_sent; }
unsigned h7mon_errors(void) { return errors; }

static void mark_dirty_rows(void)
{
	for (unsigned r = 0; r < H7MON_ROWS; r++) {
		unsigned same = first ? 0u : (cur_color[r] == shown_color[r]);
		for (unsigned i = 0; same && i < H7MON_COLS; i++) if (cur[r][i] != shown[r][i]) same = 0;
		if (!same) dirty |= 1u << r;
	}
	first = 0;
}

/* One step per call, none of them more than a few tens of microseconds. */
void h7mon_poll(const h7mon_info_t *info)
{
	if (dead || !linebuf) return;
	switch (phase) {
	case P_WAIT:                                                               /* the row is on its way: read the flag once */
		PROF_START(tp);
		if (h7lcd_blit_poll()) {
			h7lcd_end(); PROF_MAX(4, tp);
			copy_row(shown[row], cur[row]); shown_color[row] = cur_color[row]; rows_sent++; phase = P_IDLE;
		} else if (info->uptime_ms - busy_since > H7MON_BLIT_LIMIT_MS) {
			h7lcd_blit_abort(); h7lcd_end(); dirty |= 1u << row; errors++; phase = P_IDLE;
		}
		return;
	case P_FORMAT: {                                                           /* a quarter of the rows of the snapshot */
		PROF_START(tf);
		unsigned n = H7MON_ROWS / FORMAT_SLICES;
		for (unsigned r = slice * n; r < slice * n + n; r++) format_row(&snap, r, cur[r], &cur_color[r]);
		PROF_MAX(3, tf);
		if (++slice == FORMAT_SLICES) { mark_dirty_rows(); phase = P_IDLE; }
		return;
	}
	case P_RENDER: { PROF_START(tr); render_slice(row, slice); PROF_MAX(0, tr); if (++slice == RENDER_SLICES) { slice = 0; phase = P_COPY; } return; }
	case P_COPY:   { PROF_START(tc); copy_slice(slice); PROF_MAX(6, tc); if (++slice == COPY_SLICES) { slice = 0; phase = P_BEGIN; } return; }
	case P_BEGIN: {
		PROF_START(tb);
		if (!h7lcd_begin(0, row * H7_FONT_H, H7LCD_W, H7_FONT_H)) { errors++; dead = 1; return; }
		PROF_MAX(1, tb); phase = P_START; return;
	}
	case P_START: {
		PROF_START(ts);
		if (!h7lcd_blit_start(linebuf, H7MON_LINE_BYTES)) { h7lcd_end(); errors++; dead = 1; return; }
		PROF_MAX(2, ts);
		busy_since = info->uptime_ms; slice = 0; phase = P_SHADOW; return;
	}
	case P_SHADOW: {                                                           /* the shadow copy runs while the DMA does */
		PROF_START(th);
		enum { BYTES = H7MON_LINE_BYTES / SHADOW_SLICES };
		h7lcd_shadow_copy(rowbuf + slice * BYTES, BYTES); PROF_MAX(5, th);
		if (++slice == SHADOW_SLICES) phase = P_WAIT;
		return;
	}
	default: break;
	}
	if (first || info->uptime_ms - last_snap >= H7MON_PERIOD_MS) {            /* look at the unit again, once per period */
		snap = *info; last_snap = info->uptime_ms; slice = 0; phase = P_FORMAT;
		return;
	}
	if (dirty) {
		row = 0;
		while (!(dirty & (1u << row))) row++;
		dirty &= ~(1u << row); busy_row = (int)row; slice = 0; phase = P_RENDER;
	}
}
