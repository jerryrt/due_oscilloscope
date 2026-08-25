/*
 * The native port's control channel: framing and dispatch.
 *
 * Why this exists at all is in docs/control-protocol.md, and the short
 * version is that a deployed board is one cable and that cable is the
 * native port, so a control path behind the programming port does not
 * exist in deployment. The transport is a second CDC function
 * (usb_ctl_read/usb_ctl_write); this is the protocol on top of it.
 *
 * The wire format is a contract shared with Track A, which reaches it
 * through different code. It is defined here and in the document, and
 * changing one without the other is what the --track=both tests exist
 * to catch.
 */

#ifndef CTL_H
#define CTL_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#define CTL_MAGIC0   'D'
#define CTL_MAGIC1   'U'
#define CTL_MAGIC2   'E'
#define CTL_MAGIC3   'C'
#define CTL_VERSION  1

#define CTL_HDR_BYTES     16u

/*
 * One response is one packet, and that is the constraint this number
 * comes from rather than from how big any payload happens to be.
 *
 * The command endpoints are 512 bytes and single-banked, and
 * usb_ctl_write refuses rather than blocks. A response spanning two
 * packets would therefore be truncated whenever the host had not yet
 * drained the first, and the loss would be silent. 16 + 448 = 464 fits
 * one packet with room to spare, so every answer either goes whole or
 * is counted in ctl_tx_dropped.
 *
 * Anything larger than this is paged by the opcode that carries it -
 * see GET_RATE_TRACE - rather than by growing the buffer.
 */
#define CTL_MAX_PAYLOAD   448u

#define CTL_FLAG_RESPONSE (1u << 0)
#define CTL_FLAG_ERROR    (1u << 1)

/*
 * Opcodes. Grouped so the ranges mean something: 0x00xx identity and
 * liveness, 0x001x state the host both reads and writes, 0x002x
 * counters, 0x003x faults and resets.
 *
 * LOAD is in the counter range and is the one metric here that is about
 * the device rather than about the data. Everything else this board
 * exports says the loop was too slow *afterwards* - an underrun, an
 * overrun, a ring that ran dry. LOAD says how close to the edge it is
 * on a run that passes, and it is readable while the sample path is
 * blocked, which is the case the programming port has always been
 * needed for and a deployed board does not have.
 *
 * The rest are listed in docs/control-protocol.md and reach
 * cmd_execute() when they land, so that a command means the same thing
 * whichever transport delivered it.
 */
#define CTL_OP_PING       0x0001u
#define CTL_OP_IDENTITY   0x0002u
#define CTL_OP_COUNTERS   0x0020u
#define CTL_OP_OCCUPANCY  0x0021u
#define CTL_OP_RATE_TRACE 0x0022u
#define CTL_OP_LOAD       0x0024u

/*
 * Error codes. The payload of an error response is one of these
 * followed by ASCII text - the same words the console prints, because
 * the device already has to produce them for the UART transport and two
 * sets of refusal wording would drift.
 */
#define CTL_ERR_VERSION   1u   /* header version this build cannot read */
#define CTL_ERR_OPCODE    2u   /* no such command */
#define CTL_ERR_LENGTH    3u   /* payload length wrong for the opcode */
#define CTL_ERR_CRC       4u   /* header or payload did not check */

typedef struct __attribute__((packed)) {
	uint8_t  magic[4];
	uint8_t  version;
	uint8_t  flags;
	uint16_t req_id;
	uint16_t opcode;
	uint16_t length;
	uint32_t crc32;        /* over the 12 bytes above, then the payload */
} ctl_header_t;

_Static_assert(sizeof(ctl_header_t) == CTL_HDR_BYTES,
               "the control header is a wire format, not a struct layout");

/*
 * COUNTERS: what `B` prints, without printing it.
 *
 * This is the one that is polled while the board is working, and that
 * is the whole reason it exists: the console form costs 13.14 ms of
 * blocked main loop, during all of which no bulk OUT is drained. See
 * objective 0c.
 *
 * dev_us is sampled with the counters rather than fetched separately,
 * so a host differencing two of these divides by the interval the
 * device actually measured them over.
 */
typedef struct __attribute__((packed)) {
	uint32_t dev_us;
	uint32_t bytes_in;
	uint32_t produced;
	uint32_t consumed;
	uint32_t underruns;
	uint32_t isr_calls;
	uint32_t endtx_seen;
	uint32_t spans;
	uint32_t partial;
	uint32_t occ_min;
	uint32_t svc_calls;
	uint32_t loop_passes;    /* the stream side's own pass counter */
	uint32_t run_us;
	uint32_t abandoned;      /* playback stopped itself; host went away */
	uint32_t drain_polls;    /* main-loop fallback drains attempted */
} ctl_counters_t;

/*
 * OCCUPANCY: what the first two lines of `O` print.
 *
 * Variable length - the trace is only as long as it has been filled -
 * so the header's length field is what says how much came back rather
 * than a count the host has to trust twice.
 */
typedef struct __attribute__((packed)) {
	uint32_t dev_us;
	uint32_t occ_min;
	uint32_t endtx_seen;
	uint32_t run_us;
	uint32_t consumed;
	uint8_t  nbuf;           /* histogram entries following */
	uint8_t  trace_decim;
	uint16_t trace_n;        /* trace bytes after the histogram */
	/* uint32_t hist[nbuf]; then uint8_t trace[trace_n]; */
} ctl_occupancy_t;

/*
 * RATE_TRACE: paged, because it does not fit a packet.
 *
 * Request is a u16 offset. The response says what it actually returned
 * rather than assuming the host guessed the page size right, so a
 * firmware that returns fewer entries per page does not silently drop
 * the tail of the trace.
 */
typedef struct __attribute__((packed)) {
	uint8_t  decim;
	uint8_t  reserved;
	uint16_t total;          /* entries the device holds */
	uint16_t offset;         /* first entry in this page */
	uint16_t count;          /* entries in this page */
	/* uint32_t us[count]; */
} ctl_rate_page_t;

/* PING: the device's own clock, so the host can estimate offset. Not
 * frequency - that comes from the one-way timestamps the rate loop
 * already uses, which do not inherit the CDC pipeline delay. */
typedef struct __attribute__((packed)) {
	uint32_t dev_us;
	uint32_t dev_ms;
	uint32_t seq;          /* pings answered since boot */
} ctl_ping_t;

/*
 * IDENTITY: enough for a host to refuse a mismatched pairing rather
 * than misparse one. Track and versions first because they are what a
 * refusal is decided on.
 */
typedef struct __attribute__((packed)) {
	uint8_t  track;            /* 'A' or 'B' */
	uint8_t  ctl_version;
	uint8_t  frame_version;
	uint8_t  reserved;
	uint16_t frame_bytes;
	uint16_t frame_samples;
	uint32_t mck_hz;
	uint32_t adc_clock_hz;
	uint8_t  build[24];        /* __DATE__ " " __TIME__, NUL-padded */
} ctl_identity_t;

/*
 * Pump the channel. Call from the main loop.
 *
 * Also what keeps the command endpoint drained: an allocated bulk OUT
 * that nobody reads NAKs forever and hangs the host in close(), so this
 * must keep being called even when no host is talking.
 */
void ctl_service(void);

/* Counters, for `u`. Frames that arrived, frames rejected, and
 * responses that could not be written because the host stopped
 * reading - the last one is the only way a dropped answer is visible,
 * since the protocol's own rule is that silence is never valid. */
extern volatile uint32_t ctl_rx_frames;
extern volatile uint32_t ctl_rx_bad;
extern volatile uint32_t ctl_tx_dropped;

/* Print them, for `u`. Never from an ISR and never while streaming. */
void ctl_dump(void);

#endif /* CTL_H */
