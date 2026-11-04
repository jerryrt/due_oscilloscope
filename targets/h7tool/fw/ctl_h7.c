#include <string.h>
#include "ctl_h7.h"
#include "frame.h"
#include "frame16.h"

#define H7_FW_MAJOR 0
#define H7_FW_MINOR 1
#define H7_FW_PATCH 0

static uint32_t ping_seq;

static void put16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void put32(uint8_t *p, uint32_t v) { for (int i = 0; i < 4; i++) p[i] = (uint8_t)(v >> (8 * i)); }
static uint16_t get16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t get32(const uint8_t *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }

/* one reply frame: header, payload, CRC over the first 12 header bytes then the payload (same as ctl.c) */
static size_t respond(uint8_t *tx, uint16_t req_id, uint16_t opcode, uint8_t flags, const uint8_t *body, uint16_t len)
{
	tx[0] = CTL_MAGIC0; tx[1] = CTL_MAGIC1; tx[2] = CTL_MAGIC2; tx[3] = CTL_MAGIC3;
	tx[4] = CTL_VERSION; tx[5] = (uint8_t)(CTL_FLAG_RESPONSE | flags);
	put16(tx + 6, req_id); put16(tx + 8, opcode); put16(tx + 10, len);
	if (len) memcpy(tx + CTL_HDR_BYTES, body, len);
	uint32_t c = frame_crc32_update(0xffffffffu, tx, 12);
	c = frame_crc32_update(c, tx + CTL_HDR_BYTES, len);
	put32(tx + 12, ~c);
	return CTL_HDR_BYTES + len;
}

static size_t error(uint8_t *tx, uint16_t req_id, uint16_t opcode, uint16_t code, const char *text)
{
	uint8_t body[2 + 40]; size_t n = strlen(text); if (n > 40) n = 40;
	put16(body, code); memcpy(body + 2, text, n);
	return respond(tx, req_id, opcode, CTL_FLAG_ERROR, body, (uint16_t)(2 + n));
}

static void put_config(uint8_t *b, const h7_config_t *c)
{
	put32(b, c->adc_period); put32(b + 4, c->dac_period);
	b[8] = c->chmask; b[9] = c->gain1; b[10] = c->gain2; b[11] = c->coupling;
	put16(b + 12, c->gen_center); put16(b + 14, c->reserved);
}

/* An image without a restart path (image 12 and earlier) still links: the opcode then answers BUSY instead of pretending. */
__attribute__((weak)) int h7_request_bootloader(void) { return 0; }

__attribute__((weak)) int h7_explore_supported(void) { return 0; }
__attribute__((weak)) int h7_peek(uint32_t a, uint32_t *o, unsigned n) { (void)a; (void)o; (void)n; return -1; }
__attribute__((weak)) int h7_poke(uint32_t a, uint32_t v, unsigned w) { (void)a; (void)v; (void)w; return -1; }
__attribute__((weak)) int h7_explore(unsigned id, const uint32_t *a, unsigned na, uint32_t *r, unsigned *nr)
{ (void)id; (void)a; (void)na; (void)r; *nr = 0; return -2; }

size_t ctl_h7_handle(const uint8_t *rx, size_t n, uint8_t *tx)
{
	if (n < CTL_HDR_BYTES || rx[0] != CTL_MAGIC0 || rx[1] != CTL_MAGIC1 || rx[2] != CTL_MAGIC2 || rx[3] != CTL_MAGIC3)
		return 0;
	uint8_t version = rx[4];
	uint16_t req_id = get16(rx + 6), opcode = get16(rx + 8), len = get16(rx + 10);
	if (version != CTL_VERSION) return error(tx, req_id, opcode, CTL_ERR_VERSION, "version");
	if (len > CTL_MAX_PAYLOAD || (size_t)CTL_HDR_BYTES + len > n) return error(tx, req_id, opcode, CTL_ERR_LENGTH, "length");
	uint32_t c = frame_crc32_update(0xffffffffu, rx, 12);
	c = frame_crc32_update(c, rx + CTL_HDR_BYTES, len);
	if (~c != get32(rx + 12)) return error(tx, req_id, opcode, CTL_ERR_CRC, "crc");
	const uint8_t *p = rx + CTL_HDR_BYTES;
	uint8_t b[96];
	if ((opcode == H7_OP_PEEK || opcode == H7_OP_POKE || opcode == H7_OP_EXPLORE) && !h7_explore_supported())
		return error(tx, req_id, opcode, CTL_ERR_OPCODE, "opcode");

	switch (opcode) {
	case CTL_OP_PING:
		if (len) return error(tx, req_id, opcode, CTL_ERR_LENGTH, "ping takes no body");
		put32(b, h7_us()); put32(b + 4, h7_ms()); put32(b + 8, ping_seq++);
		return respond(tx, req_id, opcode, 0, b, 12);
	case CTL_OP_IDENTITY: {
		if (len) return error(tx, req_id, opcode, CTL_ERR_LENGTH, "identity takes no body");
		memset(b, 0, 42);                                   /* the whole 42-byte record: no stack bytes in the reply */
		b[0] = 'H'; b[1] = CTL_VERSION; b[2] = FRAME16_VERSION;
		b[3] = H7_FW_MAJOR; b[4] = H7_FW_MINOR; b[5] = H7_FW_PATCH;
		put16(b + 6, FRAME_BYTES); put16(b + 8, FRAME_SAMPLES);
		put32(b + 10, 200000000u);      /* the timer base every rate descends from (nominal) */
		put32(b + 14, 25000000u);       /* the ADC's EFFECTIVE clock as measured (docs/10), not the register's 50 MHz */
		b[18] = 'h'; b[19] = '7'; b[20] = '-'; b[21] = 'b'; b[22] = 'u'; b[23] = 'i'; b[24] = 'l'; b[25] = 'd'; b[26] = '-';
		uint32_t id = h7_build_id(); int k = 27;
		if (id >= 100) b[k++] = (uint8_t)('0' + id / 100 % 10);
		if (id >= 10) b[k++] = (uint8_t)('0' + id / 10 % 10);
		b[k++] = (uint8_t)('0' + id % 10);
		return respond(tx, req_id, opcode, 0, b, 42);       /* the host's struct is 42 bytes: BBBBBBHHII24s */
	}
	case CTL_OP_CAPABILITY: {
		static const uint16_t ops[] = { CTL_OP_PING, CTL_OP_IDENTITY, CTL_OP_CAPABILITY, CTL_OP_COUNTERS,
		                                H7_OP_CONFIG, H7_OP_RUN, H7_OP_PLAY, H7_OP_STATUS, H7_OP_BOOTLOADER };
		static const uint16_t more[] = { H7_OP_PEEK, H7_OP_POKE, H7_OP_EXPLORE };
		unsigned cnt = sizeof ops / sizeof ops[0];
		if (len) return error(tx, req_id, opcode, CTL_ERR_LENGTH, "capability takes no body");
		for (unsigned i = 0; i < cnt; i++) put16(b + 2 + 2 * i, ops[i]);
		if (h7_explore_supported())
			for (unsigned i = 0; i < sizeof more / sizeof more[0]; i++) put16(b + 2 + 2 * cnt++, more[i]);
		put16(b, (uint16_t)cnt);
		return respond(tx, req_id, opcode, 0, b, (uint16_t)(2 + 2 * cnt));
	}
	case CTL_OP_COUNTERS: {          /* the Due's 15-word record; what each word means on this target is in docs/19 */
		h7_status_t s; h7_get_status(&s);
		if (len) return error(tx, req_id, opcode, CTL_ERR_LENGTH, "counters takes no body");
		uint32_t w[15] = { h7_us(), s.play_consumed * 2u, s.frames, s.sent, s.play_underruns, 0, s.sent, 0, s.play_short,
		                   s.play_min_occ, 0, 0, h7_ms() * 1000u, 0, 0 };
		for (int i = 0; i < 15; i++) put32(b + 4 * i, w[i]);
		return respond(tx, req_id, opcode, 0, b, 60);
	}
	case H7_OP_CONFIG: {
		h7_config_t cfg;
		if (len == 0) { h7_get_config(&cfg); put_config(b, &cfg); return respond(tx, req_id, opcode, 0, b, 16); }
		if (len != 16) return error(tx, req_id, opcode, CTL_ERR_LENGTH, "config is 16 bytes");
		cfg.adc_period = get32(p); cfg.dac_period = get32(p + 4);
		cfg.chmask = p[8]; cfg.gain1 = p[9]; cfg.gain2 = p[10]; cfg.coupling = p[11];
		cfg.gen_center = get16(p + 12); cfg.reserved = 0;
		int r = h7_set_config(&cfg);
		if (r == -1) return error(tx, req_id, opcode, CTL_ERR_BUSY, "not while running");
		if (r) return error(tx, req_id, opcode, CTL_ERR_LENGTH, "value out of range");
		h7_get_config(&cfg); put_config(b, &cfg);
		return respond(tx, req_id, opcode, 0, b, 16);
	}
	case H7_OP_RUN:
		if (len != 1 || p[0] > 1) return error(tx, req_id, opcode, CTL_ERR_LENGTH, "run takes one byte, 0 or 1");
		b[0] = (uint8_t)h7_run(p[0]);
		return respond(tx, req_id, opcode, 0, b, 1);
	case H7_OP_PLAY: {
		if (len != 2 || p[0] > 1) return error(tx, req_id, opcode, CTL_ERR_LENGTH, "play takes cmd (0/1) and prime");
		int r = h7_play(p[0], p[1]);
		if (r < 0) return error(tx, req_id, opcode, CTL_ERR_BUSY, "refused");
		b[0] = (uint8_t)r;
		return respond(tx, req_id, opcode, 0, b, 1);
	}
	case H7_OP_STATUS: {
		h7_status_t s; h7_get_status(&s);
		if (len) return error(tx, req_id, opcode, CTL_ERR_LENGTH, "status takes no body");
		b[0] = s.running; b[1] = s.playing; b[2] = s.play_timer; b[3] = s.chmask;
		memcpy(b + 4, (const uint8_t *)&s + 4, 68);          /* the 17 words after the four bytes, little endian as in memory */
		return respond(tx, req_id, opcode, 0, b, 4 + 68);
	}
	case H7_OP_BOOTLOADER:
		if (len != 4 || memcmp(p, "BOOT", 4) != 0) return error(tx, req_id, opcode, CTL_ERR_LENGTH, "bootloader takes the 4 bytes BOOT");
		if (!h7_request_bootloader()) return error(tx, req_id, opcode, CTL_ERR_BUSY, "this image cannot restart into the boot loader");
		b[0] = 1;
		return respond(tx, req_id, opcode, 0, b, 1);
	case H7_OP_PEEK: {
		uint32_t w[16];
		if (len != 5 || p[4] < 1 || p[4] > 16 || (get32(p) & 3u)) return error(tx, req_id, opcode, CTL_ERR_LENGTH, "peek takes an aligned address and a count 1..16");
		if (h7_peek(get32(p), w, p[4])) return error(tx, req_id, opcode, H7_ERR_REFUSED, "address refused");
		for (unsigned i = 0; i < p[4]; i++) put32(b + 4 * i, w[i]);
		return respond(tx, req_id, opcode, 0, b, (uint16_t)(4u * p[4]));
	}
	case H7_OP_POKE: {
		uint32_t back;
		if (len != 9 || (p[8] != 1 && p[8] != 2 && p[8] != 4) || (get32(p) & (p[8] - 1u)))
			return error(tx, req_id, opcode, CTL_ERR_LENGTH, "poke takes an aligned address, a value and a width 1, 2 or 4");
		if (h7_poke(get32(p), get32(p + 4), p[8])) return error(tx, req_id, opcode, H7_ERR_REFUSED, "address refused");
		if (h7_peek(get32(p) & ~3u, &back, 1)) back = 0;
		put32(b, back);
		return respond(tx, req_id, opcode, 0, b, 4);
	}
	case H7_OP_EXPLORE: {
		uint32_t a[H7_EXPLORE_ARGS], r[H7_EXPLORE_RES]; unsigned na, nr = 0;
		if (len < 1 || ((len - 1u) & 3u) || (len - 1u) / 4u > H7_EXPLORE_ARGS) return error(tx, req_id, opcode, CTL_ERR_LENGTH, "explore takes an id and up to 6 words");
		na = (len - 1u) / 4u;
		for (unsigned i = 0; i < na; i++) a[i] = get32(p + 1 + 4 * i);
		if (h7_explore(p[0], a, na, r, &nr)) return error(tx, req_id, opcode, H7_ERR_REFUSED, "test or argument refused");
		if (nr > H7_EXPLORE_RES) nr = H7_EXPLORE_RES;
		uint8_t out[1 + 4 * H7_EXPLORE_RES]; out[0] = p[0];
		for (unsigned i = 0; i < nr; i++) put32(out + 1 + 4 * i, r[i]);
		return respond(tx, req_id, opcode, 0, out, (uint16_t)(1 + 4 * nr));
	}
	default:
		return error(tx, req_id, opcode, CTL_ERR_OPCODE, "opcode");
	}
}
