/*
 * Control channel framing and dispatch. See ctl.h and
 * docs/control-protocol.md.
 */

#include "ctl.h"
#include "ctl_port.h"
#include "fw_version.h"
#include "frame.h"
#include <stdio.h>
#include <string.h>

volatile uint32_t ctl_rx_frames;
volatile uint32_t ctl_rx_bad;
volatile uint32_t ctl_tx_dropped;

static const uint8_t ctl_magic[4] = {
	CTL_MAGIC0, CTL_MAGIC1, CTL_MAGIC2, CTL_MAGIC3
};

/*
 * Receive state.
 *
 * A parser that meets a frame it did not expect must reject it rather
 * than half-read it, so this hunts for the magic byte by byte and only
 * then collects a fixed-size header. Nothing about a malformed frame
 * can make it read past the length it was told, and an oversized length
 * is skipped by count rather than by looking for the next magic - which
 * would otherwise resync on a payload byte that happened to spell DUEC.
 */
enum { ST_MAGIC, ST_HEADER, ST_PAYLOAD, ST_SKIP };

static uint8_t  rx_state = ST_MAGIC;
static uint8_t  rx_magic_at;
static uint8_t  rx_hdr[CTL_HDR_BYTES];
static uint16_t rx_hdr_at;
static uint8_t  rx_payload[CTL_MAX_PAYLOAD];
static uint32_t rx_payload_at;
static uint32_t rx_skip;

static uint32_t ping_seq;

/*
 * When the last byte of a partial frame arrived.
 *
 * A host that dies mid-write - or a cable pulled between the header and
 * the payload - leaves this parser waiting for bytes that are never
 * coming, and the next frame is then read as the tail of the abandoned
 * one. Without a way back that is permanent: the deployed board's only
 * reset is the cable, so a channel that one truncated write can retire
 * is not a control channel.
 *
 * So a frame that stops arriving is abandoned. The threshold is enormous
 * against how long a frame actually takes - a 272-byte frame crosses a
 * high-speed link in microseconds - and small against a person noticing,
 * which is the right side of both.
 */
#define CTL_IDLE_US  200000u

static uint32_t rx_last_us;

/* ------------------------------------------------------------------ */
/* Transmit                                                            */
/* ------------------------------------------------------------------ */

static void ctl_respond(uint16_t req_id, uint16_t opcode, uint8_t flags,
                        const void *payload, uint16_t len)
{
	static uint8_t out[CTL_HDR_BYTES + CTL_MAX_PAYLOAD];
	ctl_header_t *h = (ctl_header_t *)out;
	uint32_t c;

	if (len > CTL_MAX_PAYLOAD)
		len = CTL_MAX_PAYLOAD;

	memcpy(h->magic, ctl_magic, sizeof(h->magic));
	h->version = CTL_VERSION;
	h->flags   = (uint8_t)(flags | CTL_FLAG_RESPONSE);
	h->req_id  = req_id;
	h->opcode  = opcode;
	h->length  = len;
	h->crc32   = 0;
	if (len)
		memcpy(out + CTL_HDR_BYTES, payload, len);

	/* Over the 12 bytes before the checksum, then the payload: the
	 * field sits inside the region it covers, which is why the CRC
	 * has a resumable form. */
	c = frame_crc32_update(0xffffffffu, out, CTL_HDR_BYTES - 4u);
	c = frame_crc32_update(c, out + CTL_HDR_BYTES, len);
	h->crc32 = ~c;

	/*
	 * One write, and no retry. ctl_port_write refuses rather than
	 * blocks when the host is not reading, and spinning here would
	 * hand a stalled host the power to stop the main loop - which is
	 * the failure the sample path is built to avoid. A lost answer is
	 * visible in ctl_tx_dropped; a wedged board is not visible at all.
	 */
	if (ctl_port_write(out, CTL_HDR_BYTES + len) != CTL_HDR_BYTES + len)
		ctl_tx_dropped++;
}

static void ctl_error(uint16_t req_id, uint16_t opcode, uint16_t code,
                      const char *text)
{
	uint8_t body[CTL_MAX_PAYLOAD];
	size_t n = strlen(text);

	if (n > sizeof(body) - 2u)
		n = sizeof(body) - 2u;
	body[0] = (uint8_t)(code & 0xff);
	body[1] = (uint8_t)(code >> 8);
	memcpy(body + 2, text, n);

	ctl_rx_bad++;
	ctl_respond(req_id, opcode, CTL_FLAG_ERROR, body, (uint16_t)(n + 2u));
}

/* ------------------------------------------------------------------ */
/* Dispatch                                                            */
/* ------------------------------------------------------------------ */

static void ctl_dispatch(const ctl_header_t *h, const uint8_t *payload,
                         uint16_t len)
{
	switch (h->opcode) {
	case CTL_OP_PING: {
		ctl_ping_t p;

		if (len != 0) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
			          "ping takes no payload");
			return;
		}
		p.dev_us = ctl_port_micros();
		p.dev_ms = ctl_port_millis();
		p.seq    = ++ping_seq;
		ctl_respond(h->req_id, h->opcode, 0, &p, sizeof(p));
		return;
	}
	case CTL_OP_IDENTITY: {
		ctl_identity_t id;

		if (len != 0) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
			          "identity takes no payload");
			return;
		}
		memset(&id, 0, sizeof(id));
		/*
		 * The track fills in what only it knows - which track it is,
		 * its clocks, its frame geometry, its build stamp.
		 */
		ctl_port_identity(&id);
		/*
		 * The three versions are answered here and never by the
		 * track. They are the contract this file *is*, and a board
		 * that reported its own idea of CTL_VERSION could disagree
		 * with the parser actually running on it - which is the one
		 * mismatch a version field exists to make impossible.
		 */
		id.ctl_version   = CTL_VERSION;
		id.frame_version = FRAME_VERSION;
		id.fw_major      = FW_VERSION_MAJOR;
		id.fw_minor      = FW_VERSION_MINOR;
		id.fw_patch      = FW_VERSION_PATCH;
		ctl_respond(h->req_id, h->opcode, 0, &id, sizeof(id));
		return;
	}
	case CTL_OP_COUNTERS: {
		ctl_counters_t ct;

		if (len != 0) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
			          "counters takes no payload");
			return;
		}
		ctl_port_counters(&ct);
		ctl_respond(h->req_id, h->opcode, 0, &ct, sizeof(ct));
		return;
	}
	case CTL_OP_STREAM_STATS: {
		ctl_stream_stats_t out;

		if (len != 0) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
			          "stream stats takes no payload");
			return;
		}
		if (!ctl_port_stream_stats(&out)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no stream stats on this track");
			return;
		}
		ctl_respond(h->req_id, h->opcode, 0, &out, sizeof(out));
		return;
	}
	case CTL_OP_BENCH: {
		ctl_bench_t out;

		if (len != 0) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
			          "bench takes no payload");
			return;
		}
		if (!ctl_port_bench(&out)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no bench counters on this track");
			return;
		}
		ctl_respond(h->req_id, h->opcode, 0, &out, sizeof(out));
		return;
	}
	case CTL_OP_OCCUPANCY: {
		static uint8_t body[CTL_MAX_PAYLOAD];
		int n;

		if (len != 0) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
			          "occupancy takes no payload");
			return;
		}
		/*
		 * The track writes the whole body, because its length comes
		 * from that track's PLAY_NBUF and PLAY_OCC_TRACE. The layout
		 * is still ctl_wire.h's and only one of those exists.
		 */
		n = ctl_port_occupancy(body, sizeof(body));
		if (n < 0) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no occupancy histogram on this track");
			return;
		}
		ctl_respond(h->req_id, h->opcode, 0, body, (uint16_t)n);
		return;
	}
	case CTL_OP_RATE_TRACE: {
		static uint8_t body[CTL_MAX_PAYLOAD];
		uint16_t off;
		int n;

		if (len != 2) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
			          "rate trace takes a u16 offset");
			return;
		}
		off = (uint16_t)((uint32_t)payload[0]
		                 | ((uint32_t)payload[1] << 8));
		n = ctl_port_rate_page(body, sizeof(body), off);
		if (n < 0) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no rate trace in this build");
			return;
		}
		ctl_respond(h->req_id, h->opcode, 0, body, (uint16_t)n);
		return;
	}
	case CTL_OP_LOAD: {
		load_report_t r;

		if (len != 0) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
			          "load takes no payload");
			return;
		}
		/*
		 * Sampled here rather than cached, so the timestamp and the
		 * counters come from one moment. A host differencing two
		 * reports needs them paired or the rate it computes is
		 * against the wrong interval - the same reason playstat
		 * carries its own dev_us.
		 */
		/*
		 * A track without a load monitor answers CTL_ERR_OPCODE
		 * rather than a report of zeroes. `available` inside the
		 * report already means "the cycle counter is not counting",
		 * which is a different statement from "this firmware does
		 * not measure this" - and a host that cannot tell them apart
		 * will read the second as an idle main loop.
		 */
		if (!ctl_port_load_sample(&r)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no load monitor on this track");
			return;
		}
		ctl_respond(h->req_id, h->opcode, 0, &r, sizeof(r));
		return;
	}
	case CTL_OP_GEN: {
		ctl_gen_t g;

		/*
		 * Zero length reads, a full payload writes and reads back.
		 * Anything else is a length error rather than a partial
		 * write: a generator half-set is a converter emitting
		 * something nobody asked for.
		 */
		if (len != 0 && len != sizeof(ctl_gen_t)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
			          "gen takes 0 bytes to read or a full "
			          "ctl_gen_t to write");
			return;
		}
		if (len == sizeof(ctl_gen_t)) {
			ctl_gen_t req;

			memcpy(&req, payload, sizeof(req));
			/*
			 * trigger_hz and output_hz are outputs and are
			 * ignored on the way in. They are properties of
			 * whatever is clocking the converter, not settings,
			 * and accepting them would let a host believe it
			 * had set a frequency it cannot set from here.
			 */
			ctl_port_gen_set(req.shape, req.points, req.sync);
		}
		if (!ctl_port_gen_get(&g)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no generator on this track");
			return;
		}
		/* The state as it ended up, never an echo: the device
		 * clamps, and a host told its own request would report a
		 * setting the converter is not running. */
		ctl_respond(h->req_id, h->opcode, 0, &g, sizeof(g));
		return;
	}
	default:
		ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
		          "no such command");
		return;
	}
}

/*
 * One description of a generator state, so both consoles print the same
 * words and neither owns them. Deliberately not a printf on either
 * track: this file has no console, and the caller decides where the
 * bytes go.
 */
const char *gen_shape_name(uint8_t s)
{
	static const char *const w[] = { "sine", "square", "ramp",
	                                 "triangle", "dc" };
	return (s < sizeof(w) / sizeof(w[0])) ? w[s] : "?";
}

const char *gen_sync_name(uint8_t s)
{
	static const char *const w[] = {
		"off (mid scale)",
		"square, one per cycle",
		"square, one per table wrap",
		"solo - DAC0 only, no sync, 2x rate",
	};
	return (s < sizeof(w) / sizeof(w[0])) ? w[s] : "?";
}

uint16_t gen_points_for(uint32_t points)
{
	uint32_t p = GEN_POINTS_MIN;

	if (points > GEN_POINTS_MAX)
		points = GEN_POINTS_MAX;
	while ((p << 1) <= points)
		p <<= 1;
	return (uint16_t)p;
}

uint16_t gen_updates_per_cycle(uint16_t points, uint8_t sync)
{
	uint16_t p = gen_points_for(points);

	/* TAG mode spends every other update on the second channel, so a
	 * cycle costs twice its points - unless the second channel has
	 * been given up, and then it costs exactly its points. */
	return (sync == GEN_SYNC_SOLO) ? p : (uint16_t)(2u * p);
}

uint32_t gen_hz_for(uint32_t trigger_hz, uint16_t points, uint8_t sync)
{
	uint16_t u = gen_updates_per_cycle(points, sync);

	return u ? trigger_hz / u : 0u;
}

int ctl_gen_describe(char *buf, unsigned long n, const ctl_gen_t *g)
{
	if (!g->trigger_hz)
		return snprintf(buf, n,
		                "gen shape %u = %s, %u pts/cycle, sync %u = %s"
		                " (no trigger running)",
		                g->shape, gen_shape_name(g->shape), g->points,
		                g->sync, gen_sync_name(g->sync));
	return snprintf(buf, n,
	                "gen shape %u = %s, %u pts/cycle, sync %u = %s"
	                " -> %lu Hz at trigger %lu Hz",
	                g->shape, gen_shape_name(g->shape), g->points,
	                g->sync, gen_sync_name(g->sync),
	                (unsigned long)g->output_hz,
	                (unsigned long)g->trigger_hz);
}

/* ------------------------------------------------------------------ */
/* Receive                                                             */
/* ------------------------------------------------------------------ */

static void ctl_frame_complete(void);

/* True when this produced a reply, so the caller can stop for the pass. */
static bool ctl_header_complete(void)
{
	const ctl_header_t *h = (const ctl_header_t *)rx_hdr;

	if (h->version != CTL_VERSION) {
		/* Answer anyway. Silence is indistinguishable from a wedged
		 * device, which is the failure this project has spent the
		 * most time on, and a version mismatch is exactly when a
		 * host most needs to be told something. */
		ctl_error(h->req_id, h->opcode, CTL_ERR_VERSION,
		          "unsupported protocol version");
		rx_skip = h->length;
		rx_state = rx_skip ? ST_SKIP : ST_MAGIC;
		return true;
	}
	if (h->length > CTL_MAX_PAYLOAD) {
		ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
		          "payload too long");
		rx_skip = h->length;
		rx_state = ST_SKIP;
		return true;
	}
	rx_payload_at = 0;
	if (h->length == 0) {
		/* Nothing more to collect. Dispatch now rather than waiting
		 * for a payload byte that is never coming - which would also
		 * swallow the first byte of the next frame. */
		ctl_frame_complete();
		return true;
	}
	rx_state = ST_PAYLOAD;
	return false;    /* nothing answered yet; the payload is still coming */
}

static void ctl_frame_complete(void)
{
	const ctl_header_t *h = (const ctl_header_t *)rx_hdr;
	uint32_t c;

	rx_state = ST_MAGIC;
	rx_magic_at = 0;

	c = frame_crc32_update(0xffffffffu, rx_hdr, CTL_HDR_BYTES - 4u);
	c = frame_crc32_update(c, rx_payload, h->length);
	if (~c != h->crc32) {
		/*
		 * The checksum covers the header, so req_id is not trusted
		 * here - it is echoed on a best-effort basis because a host
		 * that gets a reply with the wrong id can say so, and one
		 * that gets nothing cannot tell this from a dead board.
		 */
		ctl_error(h->req_id, h->opcode, CTL_ERR_CRC,
		          "checksum mismatch");
		return;
	}
	ctl_rx_frames++;
	ctl_dispatch(h, rx_payload, h->length);
}

static bool ctl_feed(uint8_t b)
{
	rx_last_us = ctl_port_micros();

	switch (rx_state) {
	case ST_MAGIC:
		/*
		 * Restart the match on the byte that failed rather than
		 * dropping it: "DUDUEC" holds a valid magic and a parser
		 * that skipped the whole run would miss it.
		 */
		if (b == ctl_magic[rx_magic_at]) {
			rx_magic_at++;
		} else {
			rx_magic_at = (b == ctl_magic[0]) ? 1u : 0u;
		}
		if (rx_magic_at == sizeof(ctl_magic)) {
			memcpy(rx_hdr, ctl_magic, sizeof(ctl_magic));
			rx_hdr_at = sizeof(ctl_magic);
			rx_magic_at = 0;
			rx_state = ST_HEADER;
		}
		return false;

	case ST_HEADER:
		rx_hdr[rx_hdr_at++] = b;
		if (rx_hdr_at >= CTL_HDR_BYTES)
			return ctl_header_complete();
		return false;

	case ST_PAYLOAD: {
		const ctl_header_t *h = (const ctl_header_t *)rx_hdr;

		if (rx_payload_at < h->length)
			rx_payload[rx_payload_at++] = b;
		if (rx_payload_at >= h->length) {
			ctl_frame_complete();
			return true;
		}
		return false;
	}
	case ST_SKIP:
		if (--rx_skip == 0)
			rx_state = ST_MAGIC;
		return false;

	default:
		rx_state = ST_MAGIC;
		return false;
	}
}

/*
 * One packet held across calls, so that stopping mid-packet is possible.
 *
 * Static and fixed: the endpoint is 512 bytes, so this is the whole
 * worst case and there is nothing to size at run time.
 */
static uint8_t  rx_buf[512];
static uint32_t rx_buf_len;
static uint32_t rx_buf_at;

void ctl_service(void)
{
	/* Abandon a frame that stopped arriving. Unsigned subtraction is
	 * correct across the ctl_port_micros() wrap; comparing timestamps directly
	 * would not be. */
	if (rx_state != ST_MAGIC && ctl_port_micros() - rx_last_us > CTL_IDLE_US) {
		rx_state = ST_MAGIC;
		rx_magic_at = 0;
		ctl_rx_bad++;
	}

	if (rx_buf_at >= rx_buf_len) {
		rx_buf_len = ctl_port_read(rx_buf, sizeof(rx_buf));
		rx_buf_at = 0;
		if (rx_buf_len == 0)
			return;
	}

	/*
	 * At most one frame per call, and the rest of the packet waits.
	 *
	 * The previous version fed up to four banks - 2048 bytes - and
	 * dispatched every frame in them. A host writing 16-byte frames
	 * back to back could therefore ask for 128 replies in a single
	 * main-loop pass, each a CRC32 over its payload and a 464-byte
	 * FIFO write: milliseconds of a loop that must keep draining bulk
	 * OUT, chosen by the peer rather than by this firmware. That is
	 * the shape of failure this project already has a name for.
	 *
	 * The worst case is now one packet scanned plus one reply built,
	 * and it does not depend on what the host sent.
	 */
	while (rx_buf_at < rx_buf_len)
		if (ctl_feed(rx_buf[rx_buf_at++]))
			return;
}

void ctl_dump(void)
{
	/*
	 * rx_state is worth printing rather than just the counters: a
	 * parser stuck mid-frame answers nothing and looks exactly like a
	 * dead channel, and the two are fixed by different things.
	 */
	printf("# ctl frames=%lu bad=%lu txdrop=%lu state=%u ping=%lu\n",
	       (unsigned long)ctl_rx_frames,
	       (unsigned long)ctl_rx_bad,
	       (unsigned long)ctl_tx_dropped,
	       (unsigned)rx_state,
	       (unsigned long)ping_seq);
	ctl_port_console_flush();
}
