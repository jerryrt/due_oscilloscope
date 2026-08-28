/*
 * Framed sample streaming over the bare-metal CDC (Track B).
 *
 * Same wire format as Track A, so the host receiver cannot tell the two
 * apart. The difference is underneath: this path never blocks, because
 * usb_cdc_write refuses rather than spins when the host stops draining.
 */

#include "sam.h"
#include "bsp.h"
#include "acq.h"
#include "gen.h"
#include "frame.h"
#include "play.h"
#include "stream.h"
#include "stream_bench.h"
#include "stream_core.h"
#include "stream_port.h"
#include "usb_cdc.h"
#include <stdio.h>
#include <string.h>

/*
 * Transport selection.
 *
 * The bare-metal UOTGHS stack does not enumerate yet (see docs), so the
 * UART transport exists so that Track B can demonstrate the same
 * end-to-end chain: timer trigger, ADC, PDC, framing, host demux and
 * tone detection. It is bandwidth-limited, not capability-limited - the
 * frame format is byte-identical to Track A's.
 */
typedef enum { XPORT_USB, XPORT_UART } xport_t;
static xport_t  xport;

volatile uint32_t stream_loop_passes;

/* Declared, reset and reported since the file was written, incremented
 * nowhere. Kept so STREAM_STATS's wire layout and its readers do not
 * move in a refactor commit; it reports the 0 it always has. */
static uint32_t refused;

/* The framer - frame building, sequencing, overrun accounting, the
 * resync rule - is lib/due_shared/src/stream_core.c now, one copy for
 * both tracks (issue #14). Its view of the capture ring layout must be
 * this track's. */
_Static_assert(STREAM_NBUF == ACQ_NBUF &&
               STREAM_BUF_SAMPLES == ACQ_BUF_SAMPLES &&
               STREAM_HDR_BYTES == ACQ_HDR_BYTES &&
               STREAM_FRAME_BYTES == ACQ_FRAME_BYTES,
               "stream_port.h ring layout must match acq.h");

/*
 * The shared framer's transport, this track's registers: bare-metal
 * uart/usb_cdc underneath, never the Arduino core's objects.
 */
size_t stream_port_write(const uint8_t *p, size_t n)
{
	if (xport == XPORT_UART) {
		for (size_t i = 0; i < n; i++)
			uart_putc_polled((char)p[i]);
		return n;
	}
	return usb_cdc_write(p, n);
}

bool stream_port_ready(void)
{
	return xport == XPORT_UART ? true : usb_cdc_ready();
}

/* The bench arms' transport: always the USB bulk pair. */
size_t usb_port_write(const uint8_t *p, size_t n)
{
	return usb_cdc_write(p, n);
}

size_t usb_port_read(uint8_t *p, size_t n)
{
	return usb_cdc_read(p, n);
}

bool usb_dma_out_done(uint32_t *bytes_left)
{
	/* One read: byte count and channel-enabled share the register, and
	 * two reads ask two different instants. See drivers/play.c. */
	uint32_t st = usb_dma_out_status();

	if (st & UOTGHS_DEVDMASTATUS_CHANN_ENB)
		return false;
	*bytes_left = (st & UOTGHS_DEVDMASTATUS_BUFF_COUNT_Msk)
	              >> UOTGHS_DEVDMASTATUS_BUFF_COUNT_Pos;
	return true;
}

void usb_dma_keepalive(void)
{
	/* Track A repairs the endpoint configuration its Arduino core
	 * rebuilds on bus reset. There is no core here, so there is
	 * nothing to repair. */
}

bool stream_start_uart(uint32_t trigger_hz)
{
	xport = XPORT_UART;
	refused = 0;
	return stream_core_start(trigger_hz, true, 2, false);
}

bool stream_start(uint32_t trigger_hz)
{
	xport = XPORT_USB;
	refused = 0;
	return stream_core_start(trigger_hz, true, 2, true);
}

/*
 * Capture only, leaving the DACC alone so play.c can drive it from the
 * host. This is what makes the full loop possible: generation and
 * capture come from different sources on independent timebases.
 */
bool stream_start_capture_only(uint32_t trigger_hz, unsigned n_channels)
{
	xport = XPORT_USB;
	refused = 0;
	return stream_core_start(trigger_hz, false, n_channels, true);
}

void stream_stop(void)
{
	stream_core_stop();
	stream_bench_stop();
}

/*
 * Whether a bench mode is consuming bulk OUT. The main loop drains the
 * endpoint when nothing does: a CDC device that stops accepting OUT
 * data wedges the host, because macOS's close() waits for in-flight
 * write URBs that a NAKing pipe never completes - and tcflush cannot
 * recall a URB already handed to the controller.
 */
bool stream_out_in_use(void)
{
	stream_bench_mode_t m = stream_bench_mode();

	return m == STREAM_BENCH_SINK || m == STREAM_BENCH_DUPLEX ||
	       m == STREAM_BENCH_SINK_DMA || m == STREAM_BENCH_DUPLEX_DMA;
}

/*
 * Whether anything is writing bulk IN. The mirror of
 * stream_out_in_use, and it exists for a sharper reason: only this
 * path may write IN while streaming, because the FIFO path owns
 * FIFOCON by hand and DMA needs the hardware to switch banks itself.
 * Anything else that wants to send on IN - the playback status record
 * the rate loop is closed on - has to ask first and stay silent when
 * this is true.
 */
bool stream_in_in_use(void)
{
	stream_bench_mode_t m = stream_bench_mode();

	return stream_core_active() ||
	       m == STREAM_BENCH_FLOOD || m == STREAM_BENCH_DUPLEX ||
	       m == STREAM_BENCH_FLOOD_DMA || m == STREAM_BENCH_DUPLEX_DMA;
}

void stream_service(void)
{
	stream_bench_service();
	stream_core_service();
}


void stream_get_stats(stream_stats_t *out)
{
	stream_core_stats_t cs;

	stream_core_get_stats(&cs);
	out->dma_frames      = cs.dma_frames;
	out->dma_stalls      = cs.dma_stalls;
	out->frames          = cs.frames;
	out->bytes           = cs.bytes;
	out->run_us          = cs.run_us;
	out->produced        = acq_produced;
	out->consumed        = acq_consumed;
	out->ring_overflow   = acq_ring_overflow;
	out->resync          = cs.resync;
	out->refused         = refused;
	out->rxbuff_overruns = acq_rxbuff_overruns;
	out->govre           = acq_govre;
	out->gen_endtx       = gen_endtx_count;
	out->usb_reset       = usb_reset_count;
	out->usb_setup       = usb_setup_count;
	out->usb_stall       = usb_stall_count;
	out->usb_configured  = usb_configured;
	out->usb_line_state  = usb_line_state;
	out->usb_cfg_fail    = usb_cfg_fail;
	out->usb_isr         = usb_isr_count;
	out->usb_devisr      = usb_last_devisr;
	out->usb_ep0isr      = usb_last_ep0isr;
	out->usb_devimr      = usb_devier_snap;
}

/*
 * The throughput division stays on the host. The device reports bytes
 * and microseconds; a rate is arithmetic over two of its counters and
 * nothing about it needs a Cortex-M3 to do it, least of all one that is
 * streaming.
 */
void stream_get_bench(stream_bench_t *out)
{
	stream_bench_stats_t bs;

	stream_bench_get_stats(&bs);
	out->mode         = bs.mode;
	out->in_bytes     = bs.in_bytes;
	out->out_bytes    = bs.out_bytes;
	out->elapsed_us   = bs.elapsed_us;
	out->resets       = bs.resets;
	out->turn         = bs.turn;
	out->dma_in_arms  = bs.dma_in_arms;
	out->dma_out_arms = bs.dma_out_arms;
	out->loop_passes  = stream_loop_passes;
}

void stream_report(void)
{
	stream_core_stats_t cs;
	uint32_t us, kbps;

	stream_core_get_stats(&cs);
	us = micros() - cs.started_us;
	kbps = us ? (uint32_t)(((uint64_t)cs.bytes * 1000ull) / us) : 0;

	/*
	 * ADC_MR read back from the peripheral, not echoed from the
	 * variable that was meant to reach it: the track/settling sweep
	 * found neither TRACKTIM nor SETTLING moving issue #5, and a
	 * negative result is only as good as the proof that the knob was
	 * connected. TRACKTIM is bits 27:24, SETTLING 21:20.
	 *
	 * Raw, and sharing this printf, because the cost of a console
	 * command is the bytes it puts on the UART and not the number of
	 * calls - decoding the two fields here read as free and measured
	 * 3.8 ms, a fifth of what `?` cost in total. Invariant 8 is about
	 * exactly that. The host decodes instead.
	 */
	printf("# dma-frames=%lu dma-stalls=%lu adcmr=%08lx acr=%08lx\n",
	       (unsigned long)cs.dma_frames, (unsigned long)cs.dma_stalls,
	       (unsigned long)acq_mr(), (unsigned long)gen_acr());
	printf("# frames=%lu bytes=%lu %lu.%03lu MB/s prod=%lu cons=%lu "
	       "ringovf=%lu resync=%lu refused=%lu rxbuff=%lu govre=%lu "
	       "endtx=%lu rst=%lu setup=%lu stall=%lu cfg=%lu dtr=%lu cfgfail=%lu\n"
	       "# usb isr=%lu devisr=%08lx ep0isr=%08lx devimr=%08lx\n",
	       (unsigned long)cs.frames, (unsigned long)cs.bytes,
	       (unsigned long)(kbps / 1000u), (unsigned long)(kbps % 1000u),
	       (unsigned long)acq_produced, (unsigned long)acq_consumed,
	       (unsigned long)acq_ring_overflow, (unsigned long)cs.resync,
	       (unsigned long)refused,
	       (unsigned long)acq_rxbuff_overruns, (unsigned long)acq_govre,
	       (unsigned long)gen_endtx_count,
	       (unsigned long)usb_reset_count, (unsigned long)usb_setup_count,
	       (unsigned long)usb_stall_count, (unsigned long)usb_configured,
	       (unsigned long)usb_line_state, (unsigned long)usb_cfg_fail,
	       (unsigned long)usb_isr_count, (unsigned long)usb_last_devisr,
	       (unsigned long)usb_last_ep0isr, (unsigned long)usb_devier_snap);
	uart_flush();
}

/* ------------------------------------------------------------------ */
/* Transport benchmarks - policy in lib/due_shared/src/stream_bench.c  */
/* ------------------------------------------------------------------ */

void stream_flood_start(void)  { stream_bench_start(STREAM_BENCH_FLOOD); }
void stream_sink_start(void)   { stream_bench_start(STREAM_BENCH_SINK); }
void stream_duplex_start(void) { stream_bench_start(STREAM_BENCH_DUPLEX); }
void stream_flood_dma_start(void)
{
	stream_bench_start(STREAM_BENCH_FLOOD_DMA);
}
void stream_sink_dma_start(void)
{
	stream_bench_start(STREAM_BENCH_SINK_DMA);
}
void stream_duplex_dma_start(void)
{
	stream_bench_start(STREAM_BENCH_DUPLEX_DMA);
}

void stream_bench_report(void)
{
	/*
	 * Report byte counts only, never a rate.
	 *
	 * The device cannot time its own benchmark reliably: opening the
	 * control port resets the board, so the window start is not related
	 * to when the host began measuring. An earlier version divided by
	 * that bogus window and reported 0.27 MB/s for a transfer the host
	 * had clocked at 3.05 MB/s, with both agreeing on the byte count.
	 *
	 * The byte counts are trustworthy and are what the host needs; it
	 * has its own clock.
	 */
	stream_bench_stats_t bs;

	stream_bench_get_stats(&bs);
	printf("# bench=%s  IN %lu B   OUT %lu B  passes=%lu arms-in=%lu arms-out=%lu\n",
	       bs.mode == STREAM_BENCH_FLOOD  ? "flood"  :
	       bs.mode == STREAM_BENCH_SINK   ? "sink"   :
	       bs.mode == STREAM_BENCH_DUPLEX ? "duplex" :
	       bs.mode == STREAM_BENCH_FLOOD_DMA ? "flood-dma" :
	       bs.mode == STREAM_BENCH_SINK_DMA ? "sink-dma" :
	       bs.mode == STREAM_BENCH_DUPLEX_DMA ? "duplex-dma" : "off",
	       (unsigned long)bs.in_bytes,
	       (unsigned long)bs.out_bytes,
	       (unsigned long)stream_loop_passes,
	       (unsigned long)bs.dma_in_arms,
	       (unsigned long)bs.dma_out_arms);
	uart_flush();
}
