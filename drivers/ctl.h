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
#define CTL_MAX_PAYLOAD   256u

#define CTL_FLAG_RESPONSE (1u << 0)
#define CTL_FLAG_ERROR    (1u << 1)

/*
 * Opcodes. Grouped so the ranges mean something: 0x00xx identity and
 * liveness, 0x001x state the host both reads and writes, 0x002x
 * counters, 0x003x faults and resets.
 *
 * Only the first two are implemented. The rest are listed in docs/control-protocol.md and reach
 * cmd_execute() when they land, so that a command means the same thing
 * whichever transport delivered it.
 */
#define CTL_OP_PING       0x0001u
#define CTL_OP_IDENTITY   0x0002u

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
