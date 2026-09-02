/*
 * The control-protocol parser, driven with arbitrary bytes.
 *
 * ctl.c is the one piece of shared firmware that consumes whatever a
 * peer chose to send: a byte-at-a-time magic hunt, a fixed header, a
 * length field the sender controls, and a dispatch that reads payload
 * bytes per opcode. Nothing about it needs a register, so ctl_port.h -
 * a record of what the protocol reaches outside itself, the same shape
 * stream_port.h has - mocks whole on a host compiler, exactly as
 * tests/framer/harness.c mocks the framer's seam.
 *
 * WHAT IS BEING TESTED IS INVARIANT 7, not only memory safety. "Every
 * main-loop pass has a bounded worst case that does not depend on what
 * a host chose to send." So the harness carries three oracles, and each
 * one is mutation-tested by tests/test_ctl_fuzz.py rather than trusted:
 *
 *   memory      ASan and UBSan, which the build supplies. rx_payload is
 *               a file-scope array, so running off it is a
 *               global-buffer-overflow rather than a silent write into
 *               whatever static follows.
 *   the reply   every byte handed to ctl_port_write is re-parsed: magic,
 *               version, a length that matches what was offered and sits
 *               inside CTL_MAX_PAYLOAD, and the CRC recomputed. A device
 *               that answers a malformed frame with a malformed frame
 *               has moved the defect to the host.
 *   bounded     ctl_service() states that it handles at most one frame
 *               per call, so a peer who packs a packet full cannot cost
 *               the main loop more than a slice of one pass. That is
 *               counted: more than one reply out of one call is the
 *               violation, and so is a pass that consumed nothing.
 *
 * THE FIRST THREE BYTES ARE THE WORLD, not the wire. A parser reached
 * through one track's answers explores one track: the capability word
 * decides whether an opcode dispatches or is refused with
 * CTL_ERR_OPCODE, and the refusals are half the code. So byte 0 is the
 * capability mask - CTL_CAP_* are bits 0..7, so it is the mask itself -
 * byte 1 chooses among the port's legal answers, byte 2 seeds how the
 * wire is cut into packets, and everything from byte 3 is what a peer
 * sent. All three are part of the input, so a crash file replays
 * exactly.
 *
 * Two entry points, one body. libFuzzer ships with the image's clang
 * and drives LLVMFuzzerTestOneInput; the standalone main() replays
 * files, runs the built-in corpus, or grinds a deterministic pseudo-
 * random stream, which is what a bench without clang gets and what the
 * board-free tier runs.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ctl.h"
#include "ctl_port.h"
#include "ctl_wire.h"
#include "frame.h"

/*
 * ctl.c's idle threshold, passed in by the build rather than copied:
 * the reset between inputs is the protocol's own abandon-a-stalled-
 * frame path, so a clock that does not step past the threshold would
 * leave the parser mid-frame and make a corpus entry depend on the one
 * before it. tests/test_ctl_fuzz.py reads the value out of ctl.c and
 * fails if it cannot find it.
 */
#ifndef CTL_IDLE_US_PROBE
#error "define CTL_IDLE_US_PROBE to ctl.c's CTL_IDLE_US"
#endif

#define WORLD_BYTES 3u

/* --- the mocked world -------------------------------------------- */

static const uint8_t *wire;
static size_t   wire_len;
static size_t   wire_at;
static bool     wire_drained;      /* a read was asked for and had none */

static uint32_t w_caps;
static uint8_t  w_flags;
static uint32_t w_chunk;           /* 0 = hand over whole packets */

static uint32_t now_us;
static uint32_t writes_this_service;
static uint32_t violations;

#define W_WRITE_REFUSES  (1u << 0)
#define W_CLOCK_JUMPS    (1u << 1)
#define W_NO_OCCUPANCY   (1u << 2)
#define W_NO_RATE_TRACE  (1u << 3)
#define W_NO_GEN         (1u << 4)
#define W_NO_SOF         (1u << 5)

static void violation(const char *what)
{
	violations++;
	fprintf(stderr, "ctl fuzz: %s\n", what);
}

/*
 * Every reply, re-parsed. The device is the only thing that produced
 * these bytes, so anything wrong with them is the device's.
 */
static void check_reply(const uint8_t *src, size_t len)
{
	ctl_header_t h;
	uint32_t c;

	if (len < CTL_HDR_BYTES) {
		violation("a reply shorter than a header");
		return;
	}
	memcpy(&h, src, sizeof(h));
	if (h.magic[0] != CTL_MAGIC0 || h.magic[1] != CTL_MAGIC1 ||
	    h.magic[2] != CTL_MAGIC2 || h.magic[3] != CTL_MAGIC3) {
		violation("a reply without the magic");
		return;
	}
	if (h.version != CTL_VERSION) {
		violation("a reply carrying another version");
		return;
	}
	if (!(h.flags & CTL_FLAG_RESPONSE)) {
		violation("a reply without CTL_FLAG_RESPONSE");
		return;
	}
	if (h.length > CTL_MAX_PAYLOAD) {
		violation("a reply declaring more than CTL_MAX_PAYLOAD");
		return;
	}
	if (len != (size_t)CTL_HDR_BYTES + h.length) {
		violation("a reply whose length field is not what was written");
		return;
	}
	if ((h.flags & CTL_FLAG_ERROR) && h.length < 2u) {
		violation("an error reply with no error code in it");
		return;
	}
	c = frame_crc32_update(0xffffffffu, src, CTL_HDR_BYTES - 4u);
	c = frame_crc32_update(c, src + CTL_HDR_BYTES, h.length);
	if (~c != h.crc32)
		violation("a reply whose CRC does not check");
}

size_t ctl_port_read(uint8_t *dst, size_t max)
{
	size_t n;

	if (wire_at >= wire_len) {
		wire_drained = true;
		return 0;
	}
	n = wire_len - wire_at;
	if (w_chunk) {
		size_t c;

		/* Where a packet boundary falls decides which frames arrive
		 * split, which is the state machine's whole reason to exist.
		 * Derived from the input, so a replay cuts identically. */
		w_chunk = w_chunk * 1103515245u + 12345u;
		c = (size_t)((w_chunk >> 16) % 131u) + 1u;
		if (n > c)
			n = c;
	}
	if (n > max)
		n = max;
	memcpy(dst, wire + wire_at, n);
	wire_at += n;
	return n;
}

size_t ctl_port_write(const uint8_t *src, size_t len)
{
	writes_this_service++;
	check_reply(src, len);
	/* A short write is backpressure, and the protocol counts it as a
	 * dropped answer rather than retrying - so refusing is a legal
	 * answer this port has to be able to give. */
	return (w_flags & W_WRITE_REFUSES) ? 0u : len;
}

uint32_t ctl_port_micros(void)
{
	/* Either a clock that never lets the idle timeout fire, or one
	 * that fires it on every call - both are worlds the parser has to
	 * survive, and the second is the abandoned-frame path. */
	now_us += (w_flags & W_CLOCK_JUMPS) ? (CTL_IDLE_US_PROBE + 1u) : 1u;
	return now_us;
}

uint32_t ctl_port_millis(void) { return now_us / 1000u; }

/*
 * ctl.c links console_out.c for ctl_dump() and the generator's one-line
 * description, neither of which the parser reaches - they are console
 * commands. The bytes are counted rather than dropped so a build that
 * did start printing from the dispatch path is visible.
 */
static unsigned long console_bytes;

void console_write(const char *s)
{
	console_bytes += strlen(s);
}

uint32_t ctl_port_out_drain_polls(void) { return 12345u; }

uint32_t ctl_port_capabilities(void) { return w_caps; }

uint32_t ctl_port_mck_hz(void) { return 78000000u; }

void ctl_port_console_flush(void) { }

void ctl_port_heartbeat_timer(uint32_t period_ms) { (void)period_ms; }

void ctl_port_identity(ctl_identity_t *out)
{
	out->track         = 'F';
	out->frame_bytes   = 2064u;
	out->frame_samples = 2032u;
	out->mck_hz        = 78000000u;
	out->adc_clock_hz  = 19500000u;
	memcpy(out->build, "fuzz", 5u);
}

void ctl_port_counters(ctl_counters_t *out)
{
	memset(out, 0, sizeof(*out));
	out->dev_us = now_us;
}

bool ctl_port_load_sample(load_report_t *out)
{
	if (!(w_caps & CTL_CAP_LOAD))
		return false;
	memset(out, 0, sizeof(*out));
	return true;
}

bool ctl_port_stream_stats(ctl_stream_stats_t *out)
{
	if (!(w_caps & CTL_CAP_STREAM_STATS))
		return false;
	memset(out, 0, sizeof(*out));
	return true;
}

bool ctl_port_bench(ctl_bench_t *out)
{
	if (!(w_caps & CTL_CAP_BENCH))
		return false;
	memset(out, 0, sizeof(*out));
	return true;
}

int ctl_port_occupancy(uint8_t *body, size_t max)
{
	size_t n;

	if (w_flags & W_NO_OCCUPANCY)
		return -1;
	/* A real track's body length comes from its own PLAY_NBUF and
	 * trace depth, so the length is varied rather than fixed - the
	 * whole legal range, 0 and max included. */
	n = ((size_t)w_flags * 3u) % (max + 1u);
	memset(body, 0x5a, n);
	return (int)n;
}

int ctl_port_rate_page(uint8_t *body, size_t max, uint16_t offset)
{
	size_t n;

	if (w_flags & W_NO_RATE_TRACE)
		return -1;
	n = ((size_t)offset * 7u) % (max + 1u);
	memset(body, 0xa5, n);
	return (int)n;
}

bool ctl_port_gen_get(ctl_gen_t *out)
{
	if (w_flags & W_NO_GEN)
		return false;
	memset(out, 0, sizeof(*out));
	out->points = 256u;
	out->amp    = 256u;
	return true;
}

void ctl_port_gen_set(uint8_t shape, uint16_t points, uint8_t sync,
                      uint16_t amp, uint16_t sync_amp)
{
	/* The arithmetic the console and the control channel share, run on
	 * whatever the peer asked for: gen_points_for clamps and rounds to
	 * a power of two and gen_hz_for divides by what it returns, so a
	 * peer choosing the divisor is exactly the interesting case. */
	(void)gen_shape_name(shape);
	(void)gen_sync_name(sync);
	(void)gen_updates_per_cycle(points, sync);
	(void)gen_hz_for(453488u, points, sync);
	(void)gen_scale_code(-2048, amp);
	(void)gen_scale_code(2047, sync_amp);
}

int ctl_port_temp(ctl_temp_t *out, uint16_t samples)
{
	unsigned which = ((unsigned)w_flags >> 6) & 3u;

	if (which == 1u)
		return CTL_TEMP_BUSY;
	if (which == 2u)
		return CTL_TEMP_UNSUPPORTED;
	memset(out, 0, sizeof(*out));
	if (samples < CTL_TEMP_SAMPLES_MIN)
		samples = CTL_TEMP_SAMPLES_MIN;
	else if (samples > CTL_TEMP_SAMPLES_MAX)
		samples = CTL_TEMP_SAMPLES_MAX;
	out->samples = samples;
	out->channel = 15u;
	return CTL_TEMP_OK;
}

int ctl_port_sof(uint32_t *frames, uint64_t *dev_us, uint32_t *ambiguous,
                 uint32_t *restarts)
{
	if (w_flags & W_NO_SOF)
		return 0;
	*frames    = (uint32_t)w_flags * 1000u;
	*dev_us    = (uint64_t)now_us;
	*ambiguous = 0u;
	*restarts  = 0u;
	return 1;
}

/* --- the drive ---------------------------------------------------- */

/*
 * One pass of ctl_service() consumes at least one byte or asks the port
 * for more, so n bytes drain in at most n calls plus one per packet, and
 * a packet is at least a byte. Twice n plus a margin is therefore a
 * bound the parser cannot legitimately exceed, and exceeding it means a
 * pass made no progress - invariant 7's liveness half, which none of the
 * other oracles would notice.
 */
static uint32_t service_until_drained(size_t n)
{
	uint32_t cap = (uint32_t)(2u * n) + 32u;
	uint32_t calls = 0;

	wire_drained = false;
	while (!wire_drained) {
		writes_this_service = 0;
		ctl_service();
		if (writes_this_service > 1u)
			violation("more than one reply out of one "
			          "ctl_service() call");
		if (++calls > cap) {
			violation("ctl_service() stopped making progress");
			break;
		}
	}
	return calls;
}

int ctl_fuzz_one(const uint8_t *data, size_t size);

int ctl_fuzz_one(const uint8_t *data, size_t size)
{
	uint32_t before = violations;

	if (size < WORLD_BYTES)
		return 0;

	w_caps  = data[0];
	w_flags = data[1];
	w_chunk = data[2];

	wire     = data + WORLD_BYTES;
	wire_len = size - WORLD_BYTES;
	wire_at  = 0;

	(void)service_until_drained(wire_len);

	/* The beat is the one frame the device sends unasked, and its
	 * cadence is the only thing a peer can have changed here. Its
	 * bytes go through the same reply oracle. */
	writes_this_service = 0;
	ctl_heartbeat_emit_isr();

	/*
	 * Leave the parser idle for the next input, through the protocol's
	 * own mechanism: a frame that stops arriving is abandoned after
	 * CTL_IDLE_US. Nothing here reaches into ctl.c's state, and a
	 * corpus entry therefore means the same thing whatever ran before
	 * it.
	 */
	now_us += CTL_IDLE_US_PROBE * 4u;
	wire_len = 0;
	wire_at  = 0;
	ctl_service();

	if (violations != before) {
		fflush(stderr);
		abort();
	}
	return 0;
}

#ifdef CTL_FUZZ_LIBFUZZER

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
	return ctl_fuzz_one(data, size);
}

#else

/* --- the built-in corpus ------------------------------------------ */

/*
 * Seeds, not tests. Their job is to put the fuzzer inside the format so
 * a campaign spends its budget on the state machine rather than on
 * rediscovering four magic bytes, and to give the board-free tier a
 * deterministic run that reaches every dispatch arm. The same bytes are
 * written out for libFuzzer by --write-seeds, so the corpus has one
 * definition.
 */
#define SEED_MAX 1400u

struct seed {
	char     name[48];
	uint8_t  buf[SEED_MAX];
	size_t   len;
};

static void seed_put(struct seed *s, const uint8_t *p, size_t n)
{
	if (s->len + n > SEED_MAX)
		return;
	memcpy(s->buf + s->len, p, n);
	s->len += n;
}

/* One frame, CRC correct unless `corrupt` asks otherwise. `declared` is
 * separate from `plen` so a seed can claim a length it does not carry. */
static void seed_frame(struct seed *s, uint8_t version, uint16_t opcode,
                       const uint8_t *payload, uint16_t plen,
                       uint16_t declared, bool corrupt)
{
	uint8_t hdr[CTL_HDR_BYTES];
	ctl_header_t *h = (ctl_header_t *)hdr;
	uint32_t c;

	h->magic[0] = CTL_MAGIC0; h->magic[1] = CTL_MAGIC1;
	h->magic[2] = CTL_MAGIC2; h->magic[3] = CTL_MAGIC3;
	h->version = version;
	h->flags   = 0;
	h->req_id  = 0x1234u;
	h->opcode  = opcode;
	h->length  = declared;
	h->crc32   = 0;
	c = frame_crc32_update(0xffffffffu, hdr, CTL_HDR_BYTES - 4u);
	c = frame_crc32_update(c, payload, plen);
	h->crc32 = corrupt ? (~c ^ 0xffu) : ~c;
	seed_put(s, hdr, sizeof(hdr));
	if (plen)
		seed_put(s, payload, plen);
}

static void seed_world(struct seed *s, uint8_t caps, uint8_t flags,
                       uint8_t chunk)
{
	uint8_t w[WORLD_BYTES];

	w[0] = caps;
	w[1] = flags;
	w[2] = chunk;
	s->len = 0;
	seed_put(s, w, sizeof(w));
}

static size_t build_corpus(struct seed *out, size_t max)
{
	static const uint16_t ops[] = {
		CTL_OP_PING, CTL_OP_IDENTITY, CTL_OP_CAPABILITY,
		CTL_OP_GEN, CTL_OP_COUNTERS, CTL_OP_OCCUPANCY,
		CTL_OP_RATE_TRACE, CTL_OP_STREAM_STATS, CTL_OP_LOAD,
		CTL_OP_BENCH, CTL_OP_TEMP, CTL_OP_HEARTBEAT,
		0x0099u,                    /* no such command */
	};
	uint8_t body[CTL_MAX_PAYLOAD];
	size_t n = 0, i;

	memset(body, 0x42, sizeof(body));

	/* Every opcode with no payload, on a board that has everything and
	 * on one that has nothing - the second is the CTL_ERR_OPCODE arm. */
	for (i = 0; i < sizeof(ops) / sizeof(ops[0]) && n < max; i++) {
		snprintf(out[n].name, sizeof(out[n].name), "op%04x-full",
		         ops[i]);
		seed_world(&out[n], 0xffu, 0x00u, 0u);
		seed_frame(&out[n], CTL_VERSION, ops[i], body, 0, 0, false);
		n++;
		if (n >= max)
			break;
		snprintf(out[n].name, sizeof(out[n].name), "op%04x-bare",
		         ops[i]);
		seed_world(&out[n], 0x00u, 0x00u, 0u);
		seed_frame(&out[n], CTL_VERSION, ops[i], body, 0, 0, false);
		n++;
	}

	/* The opcodes that take a payload, at their stated lengths. */
	if (n < max) {
		snprintf(out[n].name, sizeof(out[n].name), "gen-write");
		seed_world(&out[n], 0xffu, 0x00u, 0u);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_GEN, body,
		           (uint16_t)sizeof(ctl_gen_t),
		           (uint16_t)sizeof(ctl_gen_t), false);
		n++;
	}
	if (n < max) {
		snprintf(out[n].name, sizeof(out[n].name), "heartbeat-set");
		seed_world(&out[n], 0xffu, 0x00u, 0u);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_HEARTBEAT, body, 4u,
		           4u, false);
		n++;
	}
	if (n < max) {
		snprintf(out[n].name, sizeof(out[n].name), "temp-samples");
		seed_world(&out[n], 0xffu, 0x00u, 0u);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_TEMP, body, 2u, 2u,
		           false);
		n++;
	}
	if (n < max) {
		snprintf(out[n].name, sizeof(out[n].name), "rate-page");
		seed_world(&out[n], 0xffu, 0x00u, 0u);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_RATE_TRACE, body, 2u,
		           2u, false);
		n++;
	}

	/* The refusals, each of which is a different arm. */
	if (n < max) {
		snprintf(out[n].name, sizeof(out[n].name), "wrong-version");
		seed_world(&out[n], 0xffu, 0x00u, 0u);
		seed_frame(&out[n], (uint8_t)(CTL_VERSION + 1u), CTL_OP_PING,
		           body, 0, 0, false);
		n++;
	}
	if (n < max) {
		/* A declared length past CTL_MAX_PAYLOAD with the bytes to
		 * back it: the frame rx_payload is sized against. */
		snprintf(out[n].name, sizeof(out[n].name), "oversize-length");
		seed_world(&out[n], 0xffu, 0x00u, 0u);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_PING, body, 0,
		           (uint16_t)(CTL_MAX_PAYLOAD + 200u), false);
		seed_put(&out[n], body, sizeof(body));
		seed_put(&out[n], body, 200u);
		n++;
	}
	if (n < max) {
		snprintf(out[n].name, sizeof(out[n].name), "oversize-short");
		seed_world(&out[n], 0xffu, 0x00u, 0u);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_PING, body, 0, 0xffffu,
		           false);
		seed_put(&out[n], body, 64u);
		n++;
	}
	if (n < max) {
		snprintf(out[n].name, sizeof(out[n].name), "bad-crc");
		seed_world(&out[n], 0xffu, 0x00u, 0u);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_TEMP, body, 2u, 2u,
		           true);
		n++;
	}
	if (n < max) {
		snprintf(out[n].name, sizeof(out[n].name), "wrong-length");
		seed_world(&out[n], 0xffu, 0x00u, 0u);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_TEMP, body, 7u, 7u,
		           false);
		n++;
	}
	if (n < max) {
		/* Header and part of a payload, then silence: the abandoned
		 * frame, which only the idle timeout ends. */
		snprintf(out[n].name, sizeof(out[n].name), "truncated-idle");
		seed_world(&out[n], 0xffu, W_CLOCK_JUMPS, 0u);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_GEN, body,
		           (uint16_t)sizeof(ctl_gen_t),
		           (uint16_t)sizeof(ctl_gen_t), false);
		out[n].len -= 4u;
		n++;
	}
	if (n < max) {
		/* "DUDUEC" - a false start inside the magic. The parser
		 * restarts the match on the byte that failed rather than
		 * dropping the run, and this is the frame that proves it. */
		static const uint8_t lead[2] = { 'D', 'U' };

		snprintf(out[n].name, sizeof(out[n].name), "false-magic");
		seed_world(&out[n], 0xffu, 0x00u, 0u);
		seed_put(&out[n], lead, sizeof(lead));
		seed_frame(&out[n], CTL_VERSION, CTL_OP_PING, body, 0, 0,
		           false);
		n++;
	}
	if (n < max) {
		/*
		 * Two whole frames in one packet, chunking off. ctl_service()
		 * must answer one and leave the other, which is the bounded-
		 * work claim its own comment makes.
		 */
		snprintf(out[n].name, sizeof(out[n].name), "two-in-a-packet");
		seed_world(&out[n], 0xffu, 0x00u, 0u);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_PING, body, 0, 0,
		           false);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_IDENTITY, body, 0, 0,
		           false);
		n++;
	}
	if (n < max) {
		/* The same, cut into small packets: a frame arriving a byte
		 * at a time is the ordinary case on a bulk endpoint. */
		snprintf(out[n].name, sizeof(out[n].name), "two-split");
		seed_world(&out[n], 0xffu, 0x00u, 1u);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_PING, body, 0, 0,
		           false);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_COUNTERS, body, 0, 0,
		           false);
		n++;
	}
	if (n < max) {
		snprintf(out[n].name, sizeof(out[n].name), "write-refused");
		seed_world(&out[n], 0xffu, W_WRITE_REFUSES, 0u);
		seed_frame(&out[n], CTL_VERSION, CTL_OP_PING, body, 0, 0,
		           false);
		n++;
	}
	if (n < max) {
		snprintf(out[n].name, sizeof(out[n].name), "noise");
		seed_world(&out[n], 0xffu, 0x00u, 3u);
		seed_put(&out[n], body, 300u);
		n++;
	}
	return n;
}

static struct seed corpus[64];
static size_t corpus_n;

static int run_builtin(void)
{
	size_t i;

	corpus_n = build_corpus(corpus, sizeof(corpus) / sizeof(corpus[0]));
	for (i = 0; i < corpus_n; i++)
		ctl_fuzz_one(corpus[i].buf, corpus[i].len);
	printf("builtin %u seeds, 0 violations\n", (unsigned)corpus_n);
	return 0;
}

static int write_seeds(const char *dir)
{
	size_t i;

	corpus_n = build_corpus(corpus, sizeof(corpus) / sizeof(corpus[0]));
	for (i = 0; i < corpus_n; i++) {
		char path[512];
		FILE *f;

		snprintf(path, sizeof(path), "%s/%s.bin", dir, corpus[i].name);
		f = fopen(path, "wb");
		if (!f) {
			fprintf(stderr, "cannot write %s\n", path);
			return 2;
		}
		fwrite(corpus[i].buf, 1u, corpus[i].len, f);
		fclose(f);
	}
	printf("wrote %u seeds to %s\n", (unsigned)corpus_n, dir);
	return 0;
}

/*
 * A deterministic pseudo-random grind, seeded from the command line.
 * Not a substitute for libFuzzer - there is no coverage feedback here -
 * but it is what a bench without clang can run, and it is what makes
 * this cost a second in the board-free tier rather than a campaign.
 * Half the inputs are edits of a seed, so the format survives the noise;
 * the other half are noise, so the magic hunt is exercised too.
 */
static uint64_t rng_state;

static uint32_t rng_next(void)
{
	rng_state = rng_state * 6364136223846793005ull
	            + 1442695040888963407ull;
	return (uint32_t)(rng_state >> 33);
}

static int run_random(unsigned long runs, unsigned long seed)
{
	static uint8_t buf[SEED_MAX];
	unsigned long i;

	corpus_n = build_corpus(corpus, sizeof(corpus) / sizeof(corpus[0]));
	rng_state = (uint64_t)seed * 6364136223846793005ull + 12345u;
	for (i = 0; i < runs; i++) {
		size_t len, k, edits;

		if ((rng_next() & 1u) && corpus_n) {
			const struct seed *s = &corpus[rng_next() % corpus_n];

			len = s->len;
			memcpy(buf, s->buf, len);
			edits = rng_next() % 8u + 1u;
			for (k = 0; k < edits && len; k++)
				buf[rng_next() % len] = (uint8_t)rng_next();
		} else {
			len = rng_next() % 200u + 1u;
			for (k = 0; k < len; k++)
				buf[k] = (uint8_t)rng_next();
		}
		ctl_fuzz_one(buf, len);
	}
	printf("random %lu inputs from seed %lu, 0 violations\n", runs, seed);
	return 0;
}

static int replay(int argc, char **argv)
{
	static uint8_t buf[1u << 20];
	int i;

	for (i = 1; i < argc; i++) {
		FILE *f = fopen(argv[i], "rb");
		size_t n;

		if (!f) {
			fprintf(stderr, "cannot read %s\n", argv[i]);
			return 2;
		}
		n = fread(buf, 1u, sizeof(buf), f);
		fclose(f);
		ctl_fuzz_one(buf, n);
		printf("replayed %s (%u bytes)\n", argv[i], (unsigned)n);
	}
	return 0;
}

int main(int argc, char **argv)
{
	if (argc == 2 && !strcmp(argv[1], "--builtin"))
		return run_builtin();
	if (argc == 3 && !strcmp(argv[1], "--write-seeds"))
		return write_seeds(argv[2]);
	if (argc == 4 && !strcmp(argv[1], "--random"))
		return run_random(strtoul(argv[2], NULL, 10),
		                  strtoul(argv[3], NULL, 10));
	if (argc >= 2)
		return replay(argc, argv);
	printf("usage: fuzz_ctl --builtin | --random RUNS SEED"
	       " | --write-seeds DIR | FILE...\n");
	return 2;
}

#endif /* CTL_FUZZ_LIBFUZZER */
