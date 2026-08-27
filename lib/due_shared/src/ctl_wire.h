/*
 * The control channel's wire format, and nothing else.
 *
 * Split out of drivers/ctl.h so both tracks compile the same bytes
 * rather than two transcriptions of docs/control-protocol.md. The
 * document said the format "is defined here and in the document, and
 * changing one without the other is what the --track=both tests exist
 * to catch" - which was true, and was also a description of a contract
 * with two homes. This file is the one home; see docs/shared-source.md.
 *
 * Types and constants only. Everything that *does* something with them
 * - the parser, the dispatcher, the counters - is per-track for now and
 * lives in each track's own ctl.h.
 */

#ifndef CTL_WIRE_H
#define CTL_WIRE_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#define CTL_MAGIC0   'D'
#define CTL_MAGIC1   'U'
#define CTL_MAGIC2   'E'
#define CTL_MAGIC3   'C'
/*
 * 2: IDENTITY grew fw_major/fw_minor/fw_patch over the reserved byte,
 *    so its response is 42 bytes where 1 sent 40. A host built for 1
 *    would read frame_bytes out of the version fields.
 */
#define CTL_VERSION  3

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
#define CTL_OP_STREAM_STATS 0x0023u   /* what `?` prints */
#define CTL_OP_BENCH      0x0025u   /* what `B`'s bench half prints */

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
 * `?` over the control channel. Twenty-four counters and a uart_flush is
 * what the console form costs, on a board that is by definition
 * streaming when you want to read it - invariant 8. Field order matches
 * stream_stats_t so ctl.c is a copy and not a mapping to get wrong.
 */
typedef struct {
	uint32_t dma_frames, dma_stalls;
	uint32_t frames, bytes, run_us;
	uint32_t produced, consumed, ring_overflow, resync, refused;
	uint32_t rxbuff_overruns, govre, gen_endtx;
	uint32_t usb_reset, usb_setup, usb_stall, usb_configured;
	uint32_t usb_line_state, usb_cfg_fail;
	uint32_t usb_isr, usb_devisr, usb_ep0isr, usb_devimr;
} ctl_stream_stats_t;

/* The bench half of `B`. Bytes and microseconds; the host divides. */
typedef struct {
	uint32_t mode, in_bytes, out_bytes, elapsed_us;
	uint32_t resets, turn, dma_in_arms, dma_out_arms, loop_passes;
} ctl_bench_t;

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
	/*
	 * The firmware version, which is none of the two above: those are
	 * wire contracts a host refuses a pairing on, this is which build
	 * is on the board when both contracts are unchanged. It took the
	 * `reserved` byte and two more. See lib/due_shared/src/fw_version.h.
	 *
	 * This is the deployed path for it. A deployed board is the native
	 * port and nothing else, so the console banner - the only other
	 * place the firmware says what it is - is not reachable.
	 */
	uint8_t  fw_major;
	uint8_t  fw_minor;
	uint8_t  fw_patch;
	uint16_t frame_bytes;
	uint16_t frame_samples;
	uint32_t mck_hz;
	uint32_t adc_clock_hz;
	uint8_t  build[24];        /* __DATE__ " " __TIME__, NUL-padded */
} ctl_identity_t;

/*
 * CTL_OP_LOAD's payload. The main-loop load monitor fills it in and
 * host/control.py parses it as "<IIIIBB2x32I"; it lived in bsp/load.h,
 * which is Track B's private header, so the wire format of an opcode
 * was defined somewhere only one track could see it.
 */
#define LOAD_BUCKETS 32u

/*
 * A snapshot. Cumulative since boot or since the last load_clear(), so
 * two of them differenced give a rate and a distribution over exactly
 * the interval the caller chose - the same convention as every other
 * counter here, and the reason nothing has to agree on a window.
 */
typedef struct __attribute__((packed)) {
	uint32_t dev_us;         /* when this was taken */
	uint32_t passes;
	uint32_t max_cycles;     /* worst single pass */
	uint32_t mck_hz;         /* so the host can turn cycles into time */
	uint8_t  available;      /* 0 = the cycle counter does not count */
	uint8_t  buckets;        /* LOAD_BUCKETS, so the host can check */
	uint8_t  reserved[2];
	uint32_t hist[LOAD_BUCKETS];
} load_report_t;

#endif /* CTL_WIRE_H */
