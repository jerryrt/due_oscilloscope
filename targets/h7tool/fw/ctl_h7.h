/*
 * The H7 target's control function: the Due's control-protocol frame format (docs/control-protocol.md) served by a
 * small dispatcher of its own, because lib/due_shared/src/ctl.c hardcodes the Due's FRAME_VERSION into IDENTITY and
 * the shared tree is not edited for a second target. The wire layout, opcodes, error codes and CRC come from
 * ctl_wire.h and crc32.c, so there is one definition of the frame and a host's control.py parses these replies
 * unchanged. Portable C: no registers; everything the image owns is reached through the h7_* hooks below, which is
 * what lets tests/test_h7_ctl.py compile this file on the host and talk to it with the project's own parser.
 */
#ifndef CTL_H7_H
#define CTL_H7_H

#include <stddef.h>
#include <stdint.h>
#include "ctl_wire.h"

/* H7-only opcodes, in a range the Due never uses: a Due answers CTL_ERR_OPCODE, which is what a host should see. */
#define H7_OP_CONFIG  0x0040u   /* read (empty body) or set the acquisition and generator configuration */
#define H7_OP_RUN     0x0041u   /* u8: 1 start acquisition, 0 stop; reply u8 running */
#define H7_OP_PLAY    0x0042u   /* u8 cmd (1 start, 0 stop), u8 prime units; reply u8 playing */
#define H7_OP_STATUS  0x0043u   /* what is running and every counter */
#define H7_OP_BOOTLOADER 0x0044u  /* body: the 4 bytes "BOOT". Stops everything, replies u8 1, then restarts into the boot loader.
                                   * An image that cannot answers CTL_ERR_BUSY; a wrong body is CTL_ERR_LENGTH and does nothing. */
#define H7_OP_PEEK    0x0045u   /* hardware exploring, only in images that provide h7_explore_supported(): u32 address (4-aligned), u8 count 1..16;
                                   * reply count u32 words read in order */
#define H7_OP_POKE    0x0046u   /* u32 address, u32 value, u8 width (1, 2 or 4); reply the u32 read back from the address afterwards */
#define H7_OP_EXPLORE 0x0047u   /* u8 test id, then 0..6 u32 arguments; reply u8 id, then 0..16 u32 results. What each id does is the image's own (docs/21) */
#define H7_ERR_REFUSED 0x40u    /* error code of the three: the hook refused the address, value, test id or argument (an H7 code; the Due list ends at 5) */
#define H7_EXPLORE_ARGS 6u
#define H7_EXPLORE_RES  16u

typedef struct __attribute__((packed)) {
	uint32_t adc_period;    /* TIM3 ticks per sample at 200 MHz; >= 80 (2.5 Msps), the proven bound */
	uint32_t dac_period;    /* TIM6 ticks per update at 200 MHz; >= 40 (5 MS/s) */
	uint8_t  chmask;        /* 1 CH1, 2 CH2, 3 both */
	uint8_t  gain1, gain2;  /* gain codes 0..7 (0 is the widest range) */
	uint8_t  coupling;      /* bit 0 CH1 DC, bit 1 CH2 DC (0 = AC) */
	uint16_t gen_center;    /* DAC code for 0 V */
	uint16_t reserved;
} h7_config_t;

typedef struct __attribute__((packed)) {
	uint8_t  running, playing, play_timer, chmask;
	uint32_t adc_period, dac_period;
	uint32_t frames, lost, sent, tc_missed, ct_bad, adc_ovr;
	uint32_t play_units, play_consumed, play_underruns, play_short, play_min_occ, play_resumes;
	uint32_t starts, dma_err, build;
} h7_status_t;

/* provided by the image (main.c) or by a test stub */
uint32_t h7_us(void);
uint32_t h7_ms(void);
uint32_t h7_build_id(void);
void     h7_get_config(h7_config_t *c);
int      h7_set_config(const h7_config_t *c);   /* 0 ok, -1 not while running, -2 out of range */
int      h7_run(int on);                        /* returns running */
int      h7_play(int cmd, unsigned prime);      /* returns playing; -1 refused */
void     h7_get_status(h7_status_t *s);
/* Arm a restart into the boot loader a few milliseconds from now, after this reply has gone out. Returns 1 when armed, 0 when the
 * image has no such path (the weak default in ctl_h7.c). */
int      h7_request_bootloader(void);

/* Exploring hooks. An image that wants the three opcodes above returns 1 from h7_explore_supported() and defines the others;
 * every other image links the weak defaults, the opcodes stay out of its capability list and answer CTL_ERR_OPCODE. The hooks
 * return 0 on success, negative to refuse (-1 address or value not allowed, -2 unknown test id). */
int      h7_explore_supported(void);
int      h7_peek(uint32_t addr, uint32_t *out, unsigned count);
int      h7_poke(uint32_t addr, uint32_t value, unsigned width);
int      h7_explore(unsigned id, const uint32_t *arg, unsigned nargs, uint32_t *res, unsigned *nres);

/*
 * Handle one received packet: `n` bytes at `rx`. Writes the reply into `tx` (at least CTL_HDR_BYTES + CTL_MAX_PAYLOAD
 * bytes) and returns its length, or 0 when there is nothing to answer (not a frame at all). Bounded: no loops over the
 * payload beyond its length, no allocation.
 */
size_t ctl_h7_handle(const uint8_t *rx, size_t n, uint8_t *tx);

#endif
