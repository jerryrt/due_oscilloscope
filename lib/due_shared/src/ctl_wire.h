/*
 * The control channel's wire format, and nothing else.
 *
 * Compiled by both tracks so the format has one home rather than two
 * transcriptions of docs/control-protocol.md; see docs/shared-source.md.
 *
 * Types and constants only. Everything that *does* something with them
 * - the parser, the dispatcher, the counters - is per-track for now and
 * lives in each track's own ctl.h.
 */

#ifndef CTL_WIRE_H
#define CTL_WIRE_H

/*
 * A static assertion in both languages. The tracks are not the same
 * one: Track B is C and gets _Static_assert from C11, Track A is C++ in
 * every translation unit and spells it static_assert. This header is
 * compiled by both, so it can use neither name directly.
 */
#ifdef __cplusplus
#define CTL_STATIC_ASSERT(c, m) static_assert(c, m)
#else
#define CTL_STATIC_ASSERT(c, m) _Static_assert(c, m)
#endif



#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#define CTL_MAGIC0   'D'
#define CTL_MAGIC1   'U'
#define CTL_MAGIC2   'E'
#define CTL_MAGIC3   'C'
/* Bump on any change a host built for the old version would misparse -
 * e.g. a struct growing over what used to be reserved bytes. */
#define CTL_VERSION  3

#define CTL_HDR_BYTES     16u

/*
 * One response is one packet - the constraint this number comes from,
 * not the size of any particular payload. The command endpoints are
 * 512 bytes and single-banked and usb_ctl_write refuses rather than
 * blocks, so a response spanning two packets would be silently
 * truncated whenever the host had not yet drained the first.
 * 16 + 448 = 464 fits one packet with room to spare.
 *
 * Anything larger is paged by the opcode that carries it (see
 * GET_RATE_TRACE) rather than by growing the buffer.
 */
#define CTL_MAX_PAYLOAD   448u

#define CTL_FLAG_RESPONSE (1u << 0)
#define CTL_FLAG_ERROR    (1u << 1)

/*
 * Opcodes. Grouped so the ranges mean something: 0x00xx identity and
 * liveness, 0x001x state the host both reads and writes, 0x002x
 * counters, 0x003x faults and resets.
 *
 * LOAD is in the counter range but is about the device rather than the
 * data: everything else here says the loop was too slow *afterwards* -
 * an underrun, an overrun, a ring that ran dry - while LOAD says how
 * close to the edge it is on a run that passes.
 *
 * The rest are listed in docs/control-protocol.md and reach
 * cmd_execute() when they land, so a command means the same thing
 * whichever transport delivered it.
 */
#define CTL_OP_PING       0x0001u
#define CTL_OP_IDENTITY   0x0002u
#define CTL_OP_GEN        0x0010u   /* the signal generator: read and write */
#define CTL_OP_COUNTERS   0x0020u
#define CTL_OP_OCCUPANCY  0x0021u
#define CTL_OP_RATE_TRACE 0x0022u
#define CTL_OP_LOAD       0x0024u
#define CTL_OP_STREAM_STATS 0x0023u   /* what `?` prints */
#define CTL_OP_BENCH      0x0025u   /* what `B`'s bench half prints */
#define CTL_OP_TEMP       0x0026u   /* the SAM3X's internal temperature sensor */
#define CTL_OP_HEARTBEAT  0x0027u   /* the device's own periodic liveness beat */
#define CTL_OP_CAPABILITY 0x0003u   /* which optional opcodes this build has */

/*
 * Which optional opcodes a build implements, so a host can grey out what
 * a track has not got instead of discovering it through CTL_ERR_OPCODE.
 *
 * This cannot be derived from ctl_dispatch(): the switch is universal
 * (every opcode has a case on both tracks) and what differs is that the
 * track's ctl_port_* answers false and the shared code then returns
 * CTL_ERR_OPCODE - so a list read off the switch would claim every
 * track implements everything.
 *
 * Nor can it be probed by calling: CTL_OP_LOAD has a report-and-clear
 * variant, so running each handler to see which succeeded would destroy
 * the measurement it was asking about.
 *
 * So each track answers one word - ctl_port_capabilities() - and
 * ctl_dispatch() consults *that same word* before dispatching an
 * optional opcode, so the reply and the refusal cannot disagree.
 */
#define CTL_CAP_STREAM_STATS  (1u << 0)
#define CTL_CAP_BENCH         (1u << 1)
#define CTL_CAP_OCCUPANCY     (1u << 2)
#define CTL_CAP_RATE_TRACE    (1u << 3)
#define CTL_CAP_LOAD          (1u << 4)
#define CTL_CAP_TEMP          (1u << 5)
#define CTL_CAP_GEN           (1u << 6)
#define CTL_CAP_HEARTBEAT     (1u << 7)

/*
 * The reply carries the opcodes themselves, ascending - not the
 * bitmask. A bitmask on the wire is silent about every opcode added
 * after the host that reads it was written: an unknown bit reads as
 * "not implemented", the same defect a body of zeroes has one level up.
 * A length-prefixed list can only ever say what it does say.
 */
#define CTL_CAP_MAX_OPCODES  16u

typedef struct __attribute__((packed)) {
	uint16_t n_opcodes;
	uint16_t opcodes[CTL_CAP_MAX_OPCODES];
} ctl_capability_t;

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
/*
 * The command is implemented and well-formed, and the device will not
 * do it *now* because doing it would damage something already running.
 * Distinct from CTL_ERR_OPCODE because "this firmware cannot" and "not
 * while a capture is armed" have different remedies: a retry fixes this
 * one and never fixes that one.
 *
 * Additive, so no CTL_VERSION bump - a host that does not know the code
 * still gets an error frame with its text.
 */
#define CTL_ERR_BUSY      5u   /* implemented, but not while that is running */

typedef struct __attribute__((packed)) {
	uint8_t  magic[4];
	uint8_t  version;
	uint8_t  flags;
	uint16_t req_id;
	uint16_t opcode;
	uint16_t length;
	uint32_t crc32;        /* over the 12 bytes above, then the payload */
} ctl_header_t;

CTL_STATIC_ASSERT(sizeof(ctl_header_t) == CTL_HDR_BYTES,
               "the control header is a wire format, not a struct layout");

/*
 * COUNTERS: what `B` prints, without the cost of printing it - this is
 * the form polled while the board is working (invariant 8).
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
 * HEARTBEAT: the one frame the device sends without being asked.
 *
 * Every other opcode here is host-initiated, which is a blind spot: the
 * things worth knowing about a board are exactly the things it cannot
 * answer questions during (a hung main loop takes the console, control
 * channel and GET_LOAD dark together, since all three are answered *by*
 * that loop). A beat on its own schedule turns that silence into a
 * signal - `seq` is what makes it one: a host that sees 41, 42, 45
 * knows two beats were lost, and a host that sees nothing knows the
 * loop stopped.
 *
 * Sent as the notification form docs/control-protocol.md specifies -
 * CTL_FLAG_RESPONSE set, `req_id` zero - so no version bump is needed
 * and a host that does not know the opcode drops it.
 *
 * It carries ctl_counters_t whole rather than a summary, since the host
 * already parses that layout for CTL_OP_COUNTERS and a second, smaller
 * account of the same counters is how two numbers for one quantity get
 * into a codebase.
 */
typedef struct __attribute__((packed)) {
	uint32_t seq;             /* beats since boot; a gap is a dropped beat */
	uint32_t uptime_ms;
	uint32_t period_ms;       /* the cadence the device believes it keeps */
	uint32_t dropped;         /* beats the endpoint refused, cumulative */
	ctl_counters_t counters;  /* the existing layout, parsed by the same code */
	/*
	 * The USB host's frame clock. Every rate in this project descends
	 * from MCK, and CLAUDE.md states MCK is 78 MHz as a figure read back
	 * from the PLL settings rather than one anybody measured.
	 *
	 * It rides the heartbeat rather than an opcode of its own because a
	 * clock reference is only useful *continuously*, and the beat is
	 * already the one frame the device sends unasked. A host that wants
	 * MCK differences two beats -
	 *
	 *     mck = (d_sof_frames * 1000 * mck_nominal) / d_sof_dev_us
	 *
	 * with mck_nominal from the identity line - and needs no clock of
	 * its own anywhere in it, the advantage over timing a run from the
	 * host.
	 *
	 * The pair is latched AT a frame edge, so the two fields describe
	 * one instant; read at an arbitrary moment they would not, since the
	 * frame count steps in whole milliseconds while dev_us does not.
	 *
	 * `sof_available` is 0 where the port has never been configured, and
	 * is a flag rather than a zero count for the reason CTL_ERR_OPCODE
	 * exists: zero is a measurement and a host cannot tell it from an
	 * absence. `sof_ambiguous` counts polls too far apart to resolve
	 * FNUM's 2.048 s wrap - non-zero means sof_frames is a LOWER BOUND
	 * and no frequency may be computed from it.
	 */
	uint32_t sof_frames;      /* SOF frames in the CURRENT span */
	/*
	 * Elapsed device microseconds over the same span, 64-bit because
	 * micros() wraps every 71.6 minutes: a uint32 difference of two
	 * absolute readings is correct across one wrap and silently wrong
	 * across two. The device accumulates small wrap-safe deltas instead.
	 */
	uint64_t sof_dev_us;
	uint32_t sof_ambiguous;   /* unresolvable poll gaps, cumulative */
	/*
	 * Spans abandoned because a poll gap could not be resolved. The span
	 * RESTARTS rather than being poisoned - a health figure that goes
	 * dark for ever after one stall is the wrong shape. Non-zero means
	 * `sof_frames` counts from the last restart, not from enumeration.
	 */
	uint32_t sof_restarts;
	uint8_t  sof_available;   /* 0 = never configured; sof_frames is void */
	uint8_t  sof_reserved[3];
	/*
	 * The device's own working frequency, computed on the beat: a
	 * running estimate over the whole span since the port was
	 * configured, which needs no two beats and gets better the longer
	 * the board has been up.
	 *
	 * Cost is two 32-bit subtractions, one 64-bit multiply and one
	 * divide, once per beat - a fraction of one main-loop pass at the
	 * beat cadence's 20 ms minimum.
	 *
	 * Zero means "not yet", not "zero hertz": it is emitted until there
	 * are CTL_SOF_MIN_FRAMES of span, because a frequency from a shorter
	 * one is quantisation rather than a measurement. Zero also stands
	 * where sof_available is 0 or sof_ambiguous is non-zero.
	 */
	uint32_t mck_meas_hz;
} ctl_heartbeat_t;

/*
 * Below this many frames a computed frequency is quantisation, not a
 * measurement: one frame in 1000 is 1000 ppm, and the effect being
 * looked for is tens.
 */
#define CTL_SOF_MIN_FRAMES  60000u   /* one minute of beats */

/*
 * How often the device recomputes its own frequency, independent of how
 * often it reports it. The beat cadence is the host's to choose; this
 * is not, for invariant 7's reason - a host must not be able to scale
 * the device's work by picking a parameter.
 *
 * The estimate is CUMULATIVE, so each recomputation is over the whole
 * span since the epoch and the interval only changes how often a step
 * happens, not how large it is - the residual shrinks as the window
 * grows, which is why a ten-second update is quiet enough for a health
 * display without redrawing a figure that is still settling.
 */
#define CTL_SOF_CALC_INTERVAL_US  10000000u

/* host/control.py parses this as "<IIII" + the counters format + "<IQIIB3xI";
 * a layout that drifts from that is a silent misparse, not a link error. */
CTL_STATIC_ASSERT(sizeof(ctl_heartbeat_t) == 44u + sizeof(ctl_counters_t),
                  "ctl_heartbeat_t is a wire format, not a struct layout");

/*
 * Off by default, and the reason is invariant 7 rather than caution: a
 * board that pushes at a host which never asked is still a board
 * deciding for itself what the wire carries. The host enables it, names
 * the cadence, and can stop it. The clamp exists so the cost of a pass
 * cannot depend on what a host sent.
 */
#define CTL_HEARTBEAT_OFF_MS       0u
#define CTL_HEARTBEAT_MIN_MS      20u
#define CTL_HEARTBEAT_MAX_MS   60000u

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

/*
 * CTL_OP_TEMP's payload: the on-die temperature sensor, ADC channel 15,
 * behind ADC_ACR.TSON.
 *
 * It is not here for temperature. ADVREF is the reference for both
 * converters, so the DAC-to-ADC loopback is ratiometric and a shift in
 * ADVREF divides out to zero codes; the sensor is a bandgap-derived
 * absolute, so that term appears in it at full weight. What the reading
 * can and cannot support - no degrees without a per-part calibration,
 * an upper bound rather than a value, and nothing about the fast part
 * of reference noise - is in docs/noise.md.
 *
 * `code_x16` carries four fractional bits because a single conversion
 * is ~4 codes rms against a question about a fraction of one, so the
 * averaging has to happen here; `samples` is how many went into it.
 *
 * Refused with CTL_ERR_BUSY while a capture is armed: TSON would put
 * sensor conversions into the capture ring, which is invariant 5. The
 * device tests ADC_MR's TRGEN rather than a software flag, because the
 * hardware trigger being armed is the actual condition.
 *
 * `adc_mr` and `adc_acr` are read back from the hardware, not echoed. A
 * reading taken at a track/settling time nobody recorded is not
 * comparable with one taken at another, and the tracks do not
 * necessarily idle at the same ADC_MR.
 */

/*
 * How many conversions a reading averages. The default puts the
 * averaged noise below the quantisation floor (docs/noise.md); the
 * maximum is a bound, not a recommendation, because invariant 7 wants
 * one main-loop pass's worst case independent of what a host asked for.
 * A request past it is clamped and the report says what was averaged.
 */

/*
 * Three outcomes rather than a bool: "this track has no sensor" and
 * "not right now" are different facts with different remedies, and the
 * caller answers them with different error codes.
 */
#define CTL_TEMP_OK          1
#define CTL_TEMP_UNSUPPORTED 0
#define CTL_TEMP_BUSY      (-1)

#define CTL_TEMP_SAMPLES_DEFAULT  256u
#define CTL_TEMP_SAMPLES_MIN        1u
#define CTL_TEMP_SAMPLES_MAX     4096u

typedef struct __attribute__((packed)) {
	uint32_t dev_us;         /* when this was taken */
	uint32_t code_x16;       /* mean of `samples`, in 1/16ths of a code */
	uint16_t code_min;       /* the spread, so a host can see it is quiet */
	uint16_t code_max;
	uint16_t samples;        /* how many conversions were averaged */
	uint8_t  channel;        /* ADC channel the sensor is on: 15 here */
	uint8_t  reserved;
	uint32_t adc_mr;         /* as the hardware holds it */
	uint32_t adc_acr;        /* TSON lives here */
} ctl_temp_t;

/* host/control.py parses this as "<IIHHHBBII"; a layout that drifts from
 * that is a silent misparse, not a link error. */
CTL_STATIC_ASSERT(sizeof(ctl_temp_t) == 24u,
                  "ctl_temp_t is a wire format, not a struct layout");

/*
 * CTL_OP_GEN's payload, and the first thing in the 0x001x range - state
 * the host both reads and writes.
 *
 * One opcode for both directions: a zero-length request reads, and a
 * ctl_gen_t request writes and then reads back. The response is always
 * the state as it ended up, never an echo of the request, because the
 * device clamps - a resolution that is not a legal power of two rounds
 * down - and a host that echoed its own request would report a setting
 * the converter is not running.
 *
 * Written once, here, rather than twice: the generator itself stays two
 * independent implementations (invariant 3), but "what does
 * =<shape>,<pts>W mean" is protocol, and ctl_port_gen_get/set is the
 * only per-track part - four lines that call each track's own driver.
 *
 * Additive, so no CTL_VERSION bump. A build without this opcode answers
 * CTL_ERR_OPCODE, distinguishable from a body of zeroes.
 */
/*
 * The generator's value space. Shared because it is what travels on the
 * wire and what the console prints - not because the generator is
 * shared. The two tracks keep separate table builders and separate
 * register programming (invariant 3); what they must not keep separate
 * is the meaning of the number 1 in "=1W".
 */
#define GEN_SHAPE_SINE      0u
#define GEN_SHAPE_SQUARE    1u
#define GEN_SHAPE_RAMP      2u
#define GEN_SHAPE_TRIANGLE  3u
#define GEN_SHAPE_DC        4u
#define GEN_SHAPE_MAX       GEN_SHAPE_DC

#define GEN_SYNC_OFF        0u
#define GEN_SYNC_CYCLE      1u
#define GEN_SYNC_WRAP       2u
/*
 * SOLO is not a third kind of sync, it is the absence of the second
 * channel altogether. OFF, CYCLE and WRAP all still spend every other
 * DACC update on DAC1, because TAG mode interleaves and the table
 * alternates tags; SOLO tags every entry for DAC0, so DAC0 updates on
 * *every* trigger and the output frequency doubles:
 *
 *     OFF/CYCLE/WRAP   f = trigger_hz / (2 * points)
 *     SOLO             f = trigger_hz / points
 *
 * The cost is the sync, and with it the bench trigger and the
 * demultiplexing check - worth taking for the square, whose own edge
 * triggers a scope better than any sync does, and worth refusing for
 * anything slower-slewing.
 *
 * It also doubles the table's useful length: 512 DAC0 points per wrap
 * instead of 256. Every legal resolution still divides that, so the
 * wrap stays phase-continuous.
 */
#define GEN_SYNC_SOLO       3u
#define GEN_SYNC_MAX        GEN_SYNC_SOLO

/*
 * Points in the table, and so the resolutions that exist. A cycle may
 * spend any power of two from GEN_POINTS_MIN to the table length, and
 * nothing between: a count that does not divide the table leaves a
 * partial cycle at the PDC reload, which is a phase step in the analog
 * output once per wrap.
 */
/*
 * Output amplitude, in 1/256ths of full scale, about mid scale.
 *
 * A full-swing waveform makes a small artifact (a few DAC codes) a
 * fraction of one screen level, which no averaging recovers because the
 * quantiser is the floor - so a smaller amplitude can bring the
 * vertical resolution up without losing the motion the artifact needs.
 *
 * Centred on mid scale so the DC operating point does not move with the
 * amplitude: comparing two amplitudes is then comparing two amplitudes,
 * not two amplitudes and two bias points.
 */
#define GEN_AMP_FULL        256u
#define GEN_AMP_MIN         1u

/*
 * The sync's own amplitude, separately from the waveform's. It defaults
 * to full scale because a trigger wants every volt of edge it can get,
 * but a full-scale square switching on the pin next to the signal is
 * also a candidate source of disturbance that does not scale with the
 * signal - being able to shrink it is how that gets tested rather than
 * argued about. A DS1102E's EXT input needs of order a hundred
 * millivolts with a x1 probe, so there is room to shrink it a long way
 * before the trigger stops working.
 */
#define GEN_SYNC_AMP_FULL   256u

#define GEN_TABLE_POINTS    256u
#define GEN_POINTS_MIN      2u
#define GEN_POINTS_MAX      GEN_TABLE_POINTS

/*
 * The first functions in this header, and so the first place it needs
 * the C linkage guard: Track A compiles it as C++ and ctl.c is C.
 * Everything above is types and macros, which needed neither.
 */
#ifdef __cplusplus
extern "C" {
#endif

/* The resolution the device will adopt for a request: nearest legal
 * power of two at or below it, clamped. Rounding rather than refusing,
 * so a caller need not know which values exist - and shared, so the
 * host, the console and the control channel cannot round differently. */
uint16_t gen_points_for(uint32_t points);

/* Output frequency: one table point per trigger, and TAG mode spends
 * every other update on the second channel, so a cycle costs 2*points
 * updates. This is the resolution/frequency trade in one line. */
uint32_t gen_hz_for(uint32_t trigger_hz, uint16_t points, uint8_t sync);

/* One shape point scaled to `amp`/256 of full scale about mid, clamped
 * to the converter's 12 bits. Shared because it is arithmetic on a
 * contract value, not register programming. */
uint16_t gen_scale_code(int32_t code, uint16_t amp);

/* DACC updates one cycle costs: `points`, doubled unless the second
 * channel has been given up. The one place that arithmetic lives. */
uint16_t gen_updates_per_cycle(uint16_t points, uint8_t sync);

const char *gen_shape_name(uint8_t shape);
const char *gen_sync_name(uint8_t sync);

typedef struct __attribute__((packed)) {
	uint8_t  shape;          /* GEN_SHAPE_* */
	uint8_t  sync;           /* GEN_SYNC_*  */
	uint16_t points;         /* points per cycle, as adopted */
	uint16_t amp;            /* 1..256, 256 = full scale */
	uint16_t sync_amp;       /* 1..256, the sync's own swing */
	/*
	 * The trigger the converter is actually running at, and the
	 * output frequency that follows from it. Zero when nothing is
	 * running: the generator has a shape at all times and a frequency
	 * only while a trigger is clocking it, and a host that was handed
	 * a frequency for a stopped converter would believe a number
	 * nothing is producing.
	 */
	uint32_t trigger_hz;
	uint32_t output_hz;
} ctl_gen_t;

/*
 * The one-line human description of a generator state, so the console
 * on each track prints the same words without either one owning them.
 * Returns the length written, excluding the NUL.
 */
void ctl_gen_describe(const ctl_gen_t *g);

/*
 * How many observations `x` may take. Bounded because a host picks it:
 * invariant 7 wants the worst case of one console command fixed at
 * build time, and each observation is four settle waits.
 */
#define CTL_BLEED_MAX      15u
#define CTL_BLEED_DEFAULT   9u

/*
 * How long a DAC output is given to settle before the conversion that
 * reads it, and the ceiling a host may ask for. Both tracks wait wall
 * clock, in the same units: one command measuring two different things
 * is two sets of figures that look comparable and are not.
 *
 * It is settable because the excursion in issue #16 recurs on a fixed
 * cadence - every fourth observation, measured on this bench - and
 * only moving the cadence separates a beat against something periodic
 * from a count kept in software.
 */
#define CTL_BLEED_SETTLE_MS      10u
#define CTL_BLEED_SETTLE_MAX_MS 100u

/*
 * Summarise repeated crosstalk observations, so the two tracks print
 * the same words about the same quantity. Same pattern as
 * ctl_gen_describe(): the measurement is register work and stays per
 * track, the description is not.
 *
 * Why repeats at all: a single draw of this quantity is bimodal across
 * runs, so one reading can say "the multiplexer is clean" or "it bleeds
 * badly" depending which mode it landed on. This prints the median, the
 * range and how many observations landed in each, never one number
 * alone. Returns the length written. See docs/noise.md.
 */
void ctl_bleed_describe(const char *label,
                       const int16_t *vals, unsigned count);

/*
 * The observations themselves, in the order they were taken. A summary
 * cannot say whether the high observations arrive at random, cluster
 * into consecutive runs, or only ever land first - three different
 * defects a median and range cannot distinguish. Order is the whole
 * point, so this never sorts. Returns the length written; needs about 6
 * bytes per observation plus the label.
 */
void ctl_bleed_values(const char *label,
                     const int16_t *vals, unsigned count);

/* The raw conversion pairs behind each difference, same order. */
void ctl_bleed_raw(const char *label,
                  const uint16_t *lo, const uint16_t *hi, unsigned count);

#ifdef __cplusplus
}
#endif

#endif /* CTL_WIRE_H */
