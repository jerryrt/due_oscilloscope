/*
 * Control channel framing and dispatch. See ctl.h and
 * docs/control-protocol.md.
 */

#include "ctl.h"
#include "ctl_port.h"
#include "fw_version.h"
#include "frame.h"
#include "console_out.h"
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

/*
 * The heartbeat's whole state. Off until a host asks for it - see
 * ctl_wire.h for why a board does not decide on its own to push.
 */
static uint32_t hb_period_ms;    /* 0 = off */
static uint32_t hb_seq;
static uint32_t hb_dropped;

/*
 * Set while the main loop is inside ctl_port_write(). The heartbeat
 * interrupt skips its beat rather than interleaving bytes into the same
 * endpoint FIFO, which would put two half-frames on the wire and cost
 * the host a resync on a channel whose whole job is to be believable.
 *
 * Safe to spin-free wait on because it can never be stuck: both tracks'
 * ctl_port_write() is bounded - it tests TXINI and gives up - so the
 * main loop cannot stall inside the window this covers. A skipped beat
 * is counted, and the next one is 100 ms away.
 */
static volatile uint8_t ctl_tx_busy;

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
	ctl_tx_busy = 1;
	if (ctl_port_write(out, CTL_HDR_BYTES + len) != CTL_HDR_BYTES + len)
		ctl_tx_dropped++;
	ctl_tx_busy = 0;
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

/*
 * One source for "does this build implement that opcode".
 *
 * The dispatch refuses on this word and CTL_OP_CAPABILITY reports it, so
 * the refusal and the list are the same fact read twice rather than two
 * accounts that can drift. Issue #7.
 */
static bool ctl_have(uint32_t cap)
{
	return (ctl_port_capabilities() & cap) != 0u;
}


/*
 * Fill the SOF reference and the running frequency, issue #52.
 *
 * Shared because both fill sites - the polled reply and the unasked beat
 * - must carry the same numbers, and two copies of this arithmetic is
 * how one quantity gets two values in a codebase.
 *
 * Cost: two subtractions, a 64-bit multiply and one divide, once per
 * beat. Everything expensive was already done by the poll that latched
 * the pair.
 */
static void ctl_fill_sof(ctl_heartbeat_t *hb)
{
	uint32_t frames = 0u, ambiguous = 0u, restarts = 0u;
	uint64_t dev_us = 0u;
	int ok = ctl_port_sof(&frames, &dev_us, &ambiguous, &restarts);

	hb->sof_available = ok ? 1u : 0u;
	hb->sof_frames    = ok ? frames : 0u;
	hb->sof_dev_us    = ok ? dev_us : 0u;
	hb->sof_ambiguous = ambiguous;
	hb->sof_restarts  = restarts;
	hb->mck_meas_hz   = 0u;

	/*
	 * Zero is "not yet", and every refusal below is deliberate. A
	 * frequency from a short span is quantisation - one frame in a
	 * thousand is 1000 ppm - and an unresolved wrap makes `frames` a
	 * lower bound, so a figure computed from it would be wrong low and
	 * look like a real slow clock.
	 */
	/* A restart is not a reason to refuse - the CURRENT span is clean.
	 * Only a span too short to measure, or no reference at all, is. */
	if (!ok || frames < CTL_SOF_MIN_FRAMES || dev_us == 0u)
		return;

	/*
	 * Recomputed at most once a second, and cached between - reported in
	 * every beat, updated on the device's own tick.
	 *
	 * Not for the cost. Measured on windows-desk: the whole beat is
	 * about 110 us and this divide is about 0.26 us of it, so riding the
	 * beat would save nothing worth having.
	 *
	 * The reason is invariant 7's, applied to a measurement rather than
	 * to a pass. The beat cadence is HOST-SETTABLE from 20 ms to 60 s,
	 * so a calculation that rides it does work - and produces a figure
	 * whose meaning changes - at a rate the caller picked. The cost of a
	 * pass must not depend on what a host sent, and neither should the
	 * quality of a number the device publishes about itself.
	 *
	 * And it makes the value identical for every consumer within a
	 * second. Recomputing per beat gives two hosts reading adjacent
	 * beats two numbers for one quantity, which is the failure this
	 * struct's own docstring refuses when it declines to carry a second
	 * account of the counters.
	 *
	 * The estimate is CUMULATIVE, so a second of staleness costs well
	 * under a ppm. If it is ever made windowed, this interval stops
	 * being a nicety and becomes required: a 1 s window recomputed every
	 * 20 ms emits overlapping windows that read as independent samples.
	 */
	{
		static uint64_t last_calc_us;
		static uint32_t cached_hz;
		uint64_t age = dev_us - last_calc_us;

		if (cached_hz == 0u || age >= CTL_SOF_CALC_INTERVAL_US) {
			/* SOF is 1 kHz, so `frames` milliseconds of real time
			 * have passed while the device counted `dev_us` of its
			 * own microseconds. */
			cached_hz = (uint32_t)(((uint64_t)ctl_port_mck_hz() *
			                        dev_us) /
			                       ((uint64_t)frames * 1000u));
			last_calc_us = dev_us;
		}
		hb->mck_meas_hz = cached_hz;
	}
}

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
	case CTL_OP_CAPABILITY: {
		/*
		 * The opcodes this build dispatches, ascending, built from
		 * the same word the optional cases refuse on - so the list
		 * and the refusal cannot disagree. A capability list that
		 * can drift from the dispatch is worse than no list,
		 * because it is believed.
		 *
		 * `cap` of 0 marks an opcode every build must answer. PING,
		 * IDENTITY and CAPABILITY are mandatory because a device
		 * that could not answer them could not be asked this
		 * question; COUNTERS is mandatory because the shared
		 * dispatch has no CTL_ERR_OPCODE path for it.
		 */
		static const struct {
			uint16_t op;
			uint32_t cap;
		} known[] = {
			{ CTL_OP_PING,         0 },
			{ CTL_OP_IDENTITY,     0 },
			{ CTL_OP_CAPABILITY,   0 },
			{ CTL_OP_GEN,          CTL_CAP_GEN },
			{ CTL_OP_COUNTERS,     0 },
			{ CTL_OP_OCCUPANCY,    CTL_CAP_OCCUPANCY },
			{ CTL_OP_RATE_TRACE,   CTL_CAP_RATE_TRACE },
			{ CTL_OP_STREAM_STATS, CTL_CAP_STREAM_STATS },
			{ CTL_OP_LOAD,         CTL_CAP_LOAD },
			{ CTL_OP_BENCH,        CTL_CAP_BENCH },
			{ CTL_OP_TEMP,         CTL_CAP_TEMP },
			{ CTL_OP_HEARTBEAT,    CTL_CAP_HEARTBEAT },
		};
		ctl_capability_t out;
		uint32_t caps;
		unsigned k, w = 0;

		if (len != 0) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
			          "capability takes no payload");
			return;
		}
		memset(&out, 0, sizeof(out));
		caps = ctl_port_capabilities();
		for (k = 0; k < sizeof(known) / sizeof(known[0])
			    && w < CTL_CAP_MAX_OPCODES; k++) {
			if (known[k].cap == 0u || (caps & known[k].cap))
				out.opcodes[w++] = known[k].op;
		}
		out.n_opcodes = (uint16_t)w;
		/*
		 * Only the words actually used. A fixed-size body would pad
		 * with zero, and zero is a valid-looking opcode - the same
		 * "a body of zeroes is a measurement" trap this opcode
		 * exists to close.
		 */
		ctl_respond(h->req_id, h->opcode, 0, &out,
		            (uint16_t)(sizeof(out.n_opcodes)
		                       + w * sizeof(uint16_t)));
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

		if (!ctl_have(CTL_CAP_STREAM_STATS)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no stream stats on this track");
			return;
		}
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

		if (!ctl_have(CTL_CAP_BENCH)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no bench counters on this track");
			return;
		}
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

		if (!ctl_have(CTL_CAP_OCCUPANCY)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no occupancy histogram on this track");
			return;
		}
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

		if (!ctl_have(CTL_CAP_RATE_TRACE)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no rate trace on this track");
			return;
		}
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

		if (!ctl_have(CTL_CAP_LOAD)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no load monitor on this track");
			return;
		}
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
	case CTL_OP_HEARTBEAT: {
		ctl_heartbeat_t hb;
		uint32_t want;

		if (!ctl_have(CTL_CAP_HEARTBEAT)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no heartbeat on this track");
			return;
		}
		/*
		 * Zero length reads the setting and takes one beat now; four
		 * bytes set the cadence, 0 to stop. Both answer with the same
		 * snapshot, so "what is it doing" and "make it do this" return
		 * the one description and cannot disagree.
		 */
		if (len != 0 && len != sizeof(uint32_t)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
			          "heartbeat takes no payload or a uint32 "
			          "period in ms");
			return;
		}
		if (len == sizeof(uint32_t)) {
			memcpy(&want, payload, sizeof(want));
			if (want != CTL_HEARTBEAT_OFF_MS) {
				/* Clamped, not refused: invariant 7 wants a
				 * bounded cadence whatever a host asked for,
				 * and the reply says what it actually got. */
				if (want < CTL_HEARTBEAT_MIN_MS)
					want = CTL_HEARTBEAT_MIN_MS;
				else if (want > CTL_HEARTBEAT_MAX_MS)
					want = CTL_HEARTBEAT_MAX_MS;
			}
			hb_period_ms = want;
			/* The track owns the timer; the protocol owns the
			 * cadence. Retuning and stopping are the same call,
			 * so there is one path in and no "is it running"
			 * state to disagree with hb_period_ms. */
			ctl_port_heartbeat_timer(want);
		}

		hb.seq       = hb_seq;
		hb.uptime_ms = ctl_port_millis();
		hb.period_ms = hb_period_ms;
		hb.dropped   = hb_dropped;
		ctl_port_counters(&hb.counters);
		ctl_fill_sof(&hb);
		ctl_respond(h->req_id, h->opcode, 0, &hb, sizeof(hb));
		return;
	}


	case CTL_OP_TEMP: {
		ctl_temp_t t;
		uint16_t n = CTL_TEMP_SAMPLES_DEFAULT;
		int rc;

		if (!ctl_have(CTL_CAP_TEMP)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no temperature sensor on this track");
			return;
		}
		/*
		 * Zero length takes the default, two bytes ask for a sample
		 * count. Bounded at both ends by the port: this runs in the
		 * main loop and invariant 7 wants a worst case that does not
		 * depend on what a host sent, so a request for a million
		 * conversions is clamped rather than honoured.
		 */
		if (len != 0 && len != sizeof(uint16_t)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_LENGTH,
			          "temp takes no payload or a uint16 sample "
			          "count");
			return;
		}
		if (len == sizeof(uint16_t))
			memcpy(&n, payload, sizeof(n));

		/*
		 * Three outcomes, and a host must be able to tell the two
		 * refusals apart. CTL_ERR_OPCODE is "this firmware does not
		 * read it" and never becomes true; CTL_ERR_BUSY is "not
		 * while a capture is armed" and a retry fixes it. Neither is
		 * a body of zeroes, because code 0 is a *reading* - the
		 * bottom of the converter's range.
		 */
		rc = ctl_port_temp(&t, n);
		if (rc == CTL_TEMP_BUSY) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_BUSY,
			          "not while a capture is armed");
			return;
		}
		if (rc != CTL_TEMP_OK) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no temperature sensor on this track");
			return;
		}
		ctl_respond(h->req_id, h->opcode, 0, &t, sizeof(t));
		return;
	}
	case CTL_OP_GEN: {
		ctl_gen_t g;

		if (!ctl_have(CTL_CAP_GEN)) {
			ctl_error(h->req_id, h->opcode, CTL_ERR_OPCODE,
			          "no generator on this track");
			return;
		}
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
			ctl_port_gen_set(req.shape, req.points, req.sync,
			                 req.amp, req.sync_amp);
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

uint16_t gen_scale_code(int32_t code, uint16_t amp)
{
	int32_t centred;

	if (amp >= GEN_AMP_FULL)
		amp = GEN_AMP_FULL;
	if (amp < GEN_AMP_MIN)
		amp = GEN_AMP_MIN;
	/* About mid scale, so the bias does not move with the amplitude. */
	centred = ((code - 2048) * (int32_t)amp) / (int32_t)GEN_AMP_FULL;
	centred += 2048;
	if (centred < 0)
		centred = 0;
	if (centred > 4095)
		centred = 4095;
	return (uint16_t)centred;
}

uint32_t gen_hz_for(uint32_t trigger_hz, uint16_t points, uint8_t sync)
{
	uint16_t u = gen_updates_per_cycle(points, sync);

	return u ? trigger_hz / u : 0u;
}

/*
 * A signed value with its sign always shown - `%+d`.
 *
 * Local rather than a con_* emitter: three call sites, all in this
 * file, and console_out.h's rule for the composites is that they earn
 * their place across the firmware rather than in one function.
 */
static void con_plus(int v)
{
	if (v >= 0)
		con_ch('+');
	con_i32(v);
}

void ctl_gen_describe(const ctl_gen_t *g)
{
	con_str("gen shape ");   con_u32(g->shape);
	con_str(" = ");          con_str(gen_shape_name(g->shape));
	con_str(", ");           con_u32(g->points);
	con_str(" pts/cycle, amp "); con_u32(g->amp);
	con_str("/256, sync ");  con_u32(g->sync);
	con_str(" = ");          con_str(gen_sync_name(g->sync));
	con_str(" at ");         con_u32(g->sync_amp);
	con_str("/256");
	if (!g->trigger_hz) {
		con_str(" (no trigger running)");
		return;
	}
	con_str(" -> ");         con_u32(g->output_hz);
	con_str(" Hz at trigger "); con_u32(g->trigger_hz);
	con_str(" Hz");
}

/*
 * Median, range and the shape of the distribution - never one number.
 * See ctl_wire.h for why, which is issue #16.
 */
void ctl_bleed_describe(const char *label, const int16_t *vals,
                        unsigned count)
{
	int16_t sorted[CTL_BLEED_MAX];
	int lo, hi, median;
	unsigned i, j;

	if (count == 0u) {
		con_str("# "); con_str(label);
		con_str(": no observations"); con_nl();
		return;
	}
	if (count > CTL_BLEED_MAX)
		count = CTL_BLEED_MAX;

	/* Insertion sort: count is at most CTL_BLEED_MAX, so this is
	 * bounded at build time and needs no allocation. */
	for (i = 0; i < count; i++) {
		int16_t v = vals[i];

		for (j = i; j > 0u && sorted[j - 1u] > v; j--)
			sorted[j] = sorted[j - 1u];
		sorted[j] = v;
	}

	lo = sorted[0];
	hi = sorted[count - 1u];
	median = sorted[count / 2u];

	con_str("# "); con_str(label); con_str(": median ");
	con_plus(median); con_str(" codes, range ");
	con_plus(lo); con_str(".."); con_plus(hi);
	con_str(", n="); con_u32(count);
	/*
	 * Say when the range is wide, rather than leaving a reader to
	 * notice. A spread this size is not scatter around a value - issue
	 * #16 measured two modes - and a median alone would hide it just
	 * as effectively as the single draw did.
	 */
	if (hi - lo > 20) {
		con_str("  <- SPREAD "); con_i32(hi - lo);
		con_str(" codes, not one quantity");
	}
	con_nl();
}

/*
 * The same observations unsorted, so a host can see where in the run
 * each one landed. See ctl_wire.h for why the summary is not enough.
 */
void ctl_bleed_values(const char *label, const int16_t *vals,
                      unsigned count)
{
	unsigned i;

	if (count > CTL_BLEED_MAX)
		count = CTL_BLEED_MAX;

	con_str("# "); con_str(label); con_str(", in order:");
	for (i = 0; i < count; i++) {
		con_ch(' ');
		con_plus(vals[i]);
	}
	con_nl();
}

/*
 * The two conversions each observation subtracted, in order. Issue #16:
 * a difference hides the absolute level, and on a bare channel the
 * "control" partly measures relaxation from the previous arm's epoch -
 * visible only in the raw values. About 10 bytes per observation.
 */
void ctl_bleed_raw(const char *label, const uint16_t *lo,
                   const uint16_t *hi, unsigned count)
{
	unsigned i;

	if (count > CTL_BLEED_MAX)
		count = CTL_BLEED_MAX;

	con_str("# "); con_str(label); con_str(" raw lo/hi, in order:");
	for (i = 0; i < count; i++) {
		con_ch(' ');
		con_u32(lo[i]); con_ch('/'); con_u32(hi[i]);
	}
	con_nl();
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

/*
 * One heartbeat, sent from the track's timer interrupt.
 *
 * **Why this runs in interrupt context, against the shape invariant 7
 * asks for.** "An ISR notices, the main loop acts" is the right rule for
 * work the loop can do later, and this is the one piece of traffic for
 * which that is exactly wrong: the fact worth reporting is that the main
 * loop has stopped, and a beat the loop sends cannot report it. Issue
 * #33 stalled Track A's loop and the console, the control channel and
 * GET_LOAD went dark together - the board looked identical to one that
 * had been unplugged, and the only way anyone got it back also reset it
 * and erased the evidence.
 *
 * Measured on linux-x1 with the loop deliberately stalled: 167 of 199
 * beats arrived carrying a `loop_passes` that never moved, while `seq`
 * and `uptime_ms` advanced. So the beat does not merely survive the
 * stall - it carries the proof of it, live, on a deployed board with no
 * console and no debugger.
 *
 * Invariant 6 forbids printf from an ISR and the reason it gives is
 * cost: ~3.5 ms against a 0.95 us conversion. This is not that. It is a
 * fixed 92-byte frame, a CRC32 over those bytes, and a bounded FIFO
 * write that gives up when no bank is free - tens of microseconds, at a
 * cadence the host chose and the device clamped. Nothing here loops on
 * a hardware flag.
 *
 * It is off until a host asks for it, so a board that nobody is
 * listening to does none of this.
 */
void ctl_heartbeat_emit_isr(void)
{
	/* Its own buffer. ctl_respond()'s is being written by the main
	 * loop whenever ctl_tx_busy is set, and sharing one would put half
	 * a response inside a beat. */
	static uint8_t out[CTL_HDR_BYTES + sizeof(ctl_heartbeat_t)];
	ctl_header_t *h = (ctl_header_t *)out;
	ctl_heartbeat_t hb;
	uint32_t c;

	if (hb_period_ms == CTL_HEARTBEAT_OFF_MS)
		return;
	if (ctl_tx_busy) {
		/* The main loop owns the endpoint for the next few
		 * microseconds. Skipping is visible - the host sees the gap
		 * in seq - and interleaving would not be. */
		hb_dropped++;
		return;
	}

	hb.seq       = ++hb_seq;
	hb.uptime_ms = ctl_port_millis();
	hb.period_ms = hb_period_ms;
	hb.dropped   = hb_dropped;
	ctl_port_counters(&hb.counters);
	ctl_fill_sof(&hb);

	memcpy(h->magic, ctl_magic, sizeof(h->magic));
	h->version = CTL_VERSION;
	h->flags   = CTL_FLAG_RESPONSE;   /* the notification form */
	h->req_id  = 0;                   /* nobody asked */
	h->opcode  = CTL_OP_HEARTBEAT;
	h->length  = (uint16_t)sizeof(hb);
	h->crc32   = 0;
	memcpy(out + CTL_HDR_BYTES, &hb, sizeof(hb));
	c = frame_crc32_update(0xffffffffu, out, CTL_HDR_BYTES - 4u);
	c = frame_crc32_update(c, out + CTL_HDR_BYTES, sizeof(hb));
	h->crc32 = ~c;

	if (ctl_port_write(out, sizeof(out)) != sizeof(out))
		hb_dropped++;
}

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
	con_str("# ctl ");
	con_kv_u32("frames", ctl_rx_frames);   con_ch(' ');
	con_kv_u32("bad", ctl_rx_bad);         con_ch(' ');
	con_kv_u32("txdrop", ctl_tx_dropped);  con_ch(' ');
	con_kv_u32("state", rx_state);         con_ch(' ');
	con_kv_u32("ping", ping_seq);          con_nl();
	ctl_port_console_flush();
}
