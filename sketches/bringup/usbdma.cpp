#include <Arduino.h>
#include "USB/USBDesc.h"          /* CDC_RX, CDC_TX */
#include "usbdma.h"
#include "ctlusb.h"

/*
 * UOTGHS_DEVDMA is indexed from endpoint 1, so endpoint n uses index
 * n-1. Endpoint 0 has no DMA channel, which is fine: control transfers
 * are tiny, rare, and stay with the core.
 *
 * The Arduino CDC puts bulk OUT on endpoint 2 and bulk IN on endpoint 3,
 * so the channels differ from Track B's by one. Everything else about
 * the controller is identical.
 */
#define DMA_OUT_CH  (CDC_RX - 1u)
#define DMA_IN_CH   (CDC_TX - 1u)

volatile uint32_t usbdma_rebuilds;
volatile uint32_t usb_in_activity;
volatile uint32_t usb_out_activity;

static bool mode_in, mode_out;

bool usbdma_out_claimed(void) { return mode_out; }

bool usbdma_ready(void)
{
	return SerialUSB.dtr();
}

/*
 * DMA needs AUTOSW: with it the controller frees a drained OUT bank (and
 * validates a filled IN bank) by itself, which is what lets one transfer
 * span many packets. Without it the DMA drains the first bank and then
 * waits forever for a bank switch that never comes.
 *
 * The write must happen with the endpoint ENABLED. Measured on this
 * part by Track B: a DEVEPTCFG write while EPEN is clear is silently
 * ignored, so a disable-write-enable sequence reads back without AUTOSW
 * and recreates the stall. The live write sticks and CFGOK stays set.
 */
/*
 * WARNING for whoever adds the control channel to this track.
 *
 * This writes DEVEPTCFG with ALLOC still set, which re-allocates the
 * endpoint - and datasheet 40.5.1.6 says the x+1 window then slides up
 * and loses its data while x+2 and above stay put. It is harmless here
 * only because this track stops at EP3, so re-allocating EP2 slides EP3
 * and nothing sits above it.
 *
 * Track B was in exactly this position until EP4-EP6 arrived, at which
 * point the hazard went live and cost a session: the host wedged in
 * close() whenever the control channel was in use, because a control
 * transfer was in flight while a mode switch slid its endpoint's memory
 * out from under it. drivers/usb_cdc.c carries the fix - skip the write
 * when the bit already holds the wanted value, and re-allocate the
 * endpoints above in ascending order when it does not. Port the fix
 * with the feature, not after it.
 */
static void ep_apply_autosw(uint32_t ep, bool on)
{
	uint32_t cfg = UOTGHS->UOTGHS_DEVEPTCFG[ep];

	/*
	 * A write that changes nothing must not happen at all, because on
	 * this controller there is no such thing: every DEVEPTCFG write
	 * carries ALLOC and re-allocates. Most calls here are redundant -
	 * releasing a mode that was never claimed - and they were paying
	 * full price for it. That is half of the fix named in the warning
	 * above; the other half is below, and it is no longer inert - the
	 * control channel brought EP4-6 into existence, so a write here
	 * really does slide a window that matters.
	 */
	if (!!(cfg & UOTGHS_DEVEPTCFG_AUTOSW) == on)
		return;

	if (on)
		cfg |= UOTGHS_DEVEPTCFG_AUTOSW;
	else
		cfg &= ~UOTGHS_DEVEPTCFG_AUTOSW;

	UOTGHS->UOTGHS_DEVEPTCFG[ep] = cfg;

	/*
	 * The other half. This write re-allocated `ep`, which slides
	 * the window of ep+1 and loses whatever was in it (40.5.1.6).
	 * The control endpoints sit above both EP2 and EP3, so put
	 * them back, ascending, before anything reads them.
	 */
	ctlusb_realloc_endpoints();
}

/*
 * Take the endpoint away from the core's interrupt handler.
 *
 * USBCore's ISR answers a CDC_RX endpoint interrupt by calling
 * Serial_::accept(), which drains the FIFO into its 512-byte ring one
 * byte at a time. That is the path this whole file exists to replace,
 * and it must not run: bytes it steals are bytes the DMA will never
 * see, and the sample stream would silently lose its alignment.
 */
static void ep_take(uint32_t ep)
{
	UOTGHS->UOTGHS_DEVEPTIDR[ep] = UOTGHS_DEVEPTIDR_RXOUTEC;
	UOTGHS->UOTGHS_DEVIDR = UOTGHS_DEVIDR_PEP_0 << ep;
}

static void ep_give_back(uint32_t ep)
{
	UOTGHS->UOTGHS_DEVEPTIER[ep] = UOTGHS_DEVEPTIER_RXOUTES;
	UOTGHS->UOTGHS_DEVIER = UOTGHS_DEVIER_PEP_0 << ep;
}

/*
 * Reset one endpoint's FIFO and bank state, keeping its configuration.
 *
 * Stopping a DMA mid-transfer leaves the endpoint holding a bank that
 * is partially filled and never validated. Nothing frees it: the next
 * transfer waits for a free bank that cannot arrive, which presents as
 * a channel stuck busy forever after exactly one short transfer. EPRST
 * clears the banks and the data toggle, which is what a host expects
 * after the reconfiguration that caused this in the first place.
 */
static void ep_reset_fifo(uint32_t ep)
{
	UOTGHS->UOTGHS_DEVEPT |= UOTGHS_DEVEPT_EPRST0 << ep;
	UOTGHS->UOTGHS_DEVEPT &= ~(UOTGHS_DEVEPT_EPRST0 << ep);
}

static void dma_channel_stop(uint32_t ch)
{
	if (!(UOTGHS->UOTGHS_DEVDMA[ch].UOTGHS_DEVDMASTATUS
	      & UOTGHS_DEVDMASTATUS_CHANN_ENB))
		return;
	UOTGHS->UOTGHS_DEVDMA[ch].UOTGHS_DEVDMACONTROL = 0;
	/* The controller stops at the next packet boundary. */
	for (uint32_t spin = 0; spin < 100000u; spin++)
		if (!(UOTGHS->UOTGHS_DEVDMA[ch].UOTGHS_DEVDMASTATUS
		      & UOTGHS_DEVDMASTATUS_CHANN_ENB))
			break;
}

void usbdma_mode_out(bool on)
{
	dma_channel_stop(DMA_OUT_CH);
	mode_out = on;

	if (on)
		ep_take(CDC_RX);
	else
		ep_give_back(CDC_RX);

	ep_apply_autosw(CDC_RX, on);
}

void usbdma_mode_in(bool on)
{
	dma_channel_stop(DMA_IN_CH);
	mode_in = on;
	ep_apply_autosw(CDC_TX, on);
}

void usbdma_mode(bool in_dma, bool out_dma)
{
	usbdma_mode_in(in_dma);
	usbdma_mode_out(out_dma);
}

/*
 * Put the endpoint back the way we need it after the core rebuilt it.
 *
 * UDD_InitEP runs on every bus reset and again on SET_CONFIGURATION,
 * and it writes DEVEPTCFG without AUTOSW and re-enables its own receive
 * interrupt. There is no callback to hook, so this is polled from the
 * main loop: two register reads when nothing has changed, which is
 * cheap enough to run unconditionally.
 *
 * The rebuild counter is the diagnostic that matters. Nonzero right
 * after enumeration is normal; climbing during a run means the link is
 * resetting underneath, which looks like data corruption if you do not
 * know to check.
 */
void usbdma_keepalive(void)
{
	/* The core re-enables every endpoint's interrupt on bus reset and
	 * SET_CONFIGURATION, including the control endpoints it knows
	 * nothing about. Mask them again here, on the same schedule and
	 * for the same reason this function already exists. */
	ctlusb_quiesce_interrupts();

	bool clobbered = false;

	/*
	 * Only meaningful once the host has the port open. With the
	 * endpoint disabled a DEVEPTCFG write is silently ignored on this
	 * part, so before that this would count a "rebuild" on every pass
	 * and bury the one signal the counter exists to give. Nothing is
	 * armed while the port is closed either, so there is nothing to
	 * protect yet.
	 */
	if (!usbdma_ready())
		return;

	if (mode_out) {
		if (!(UOTGHS->UOTGHS_DEVEPTCFG[CDC_RX] & UOTGHS_DEVEPTCFG_AUTOSW))
			clobbered = true;
		if (UOTGHS->UOTGHS_DEVIMR & (UOTGHS_DEVIMR_PEP_0 << CDC_RX))
			clobbered = true;
	}
	if (mode_in &&
	    !(UOTGHS->UOTGHS_DEVEPTCFG[CDC_TX] & UOTGHS_DEVEPTCFG_AUTOSW))
		clobbered = true;

	if (!clobbered)
		return;

	/*
	 * A transfer that was in flight when the core rebuilt the endpoint
	 * is stalled for good: the bank switch it waits for cannot happen
	 * across a reconfiguration. Every caller polls "is the channel
	 * still busy" before re-arming, so a stalled channel wedges that
	 * direction permanently - which is exactly what it did, as an
	 * intermittent one-transfer IN stall whenever enumeration landed
	 * just after the first arm.
	 *
	 * Stop the channels first, then restore the mode, and let the
	 * callers re-arm from a known state.
	 */
	if (mode_out) {
		dma_channel_stop(DMA_OUT_CH);
		ep_reset_fifo(CDC_RX);
		ep_take(CDC_RX);
		ep_apply_autosw(CDC_RX, true);
	}
	if (mode_in) {
		dma_channel_stop(DMA_IN_CH);
		ep_reset_fifo(CDC_TX);
		ep_apply_autosw(CDC_TX, true);
	}

	usbdma_rebuilds++;
}

/* ------------------------------------------------------------------ */
/* OUT: host -> device                                                 */
/* ------------------------------------------------------------------ */

bool usbdma_out_busy(void)
{
	return (UOTGHS->UOTGHS_DEVDMA[DMA_OUT_CH].UOTGHS_DEVDMASTATUS
	        & UOTGHS_DEVDMASTATUS_CHANN_ENB) != 0;
}

/*
 * One read of DEVDMASTATUS, decoded by the caller.
 *
 * BUFF_COUNT counts down as the controller lands bytes, so a caller can
 * follow progress mid-transfer rather than only at the end - a
 * multi-slot span takes milliseconds to complete and a consumer that
 * only learned of new data at completion would drain the ring against a
 * frozen counter.
 *
 * Byte count and channel-enabled live in the same register, and reading
 * it twice asks two different instants whether the transfer finished
 * and how far it got. The answers disagree exactly when the transfer
 * ends between them, which is the moment the caller most needs them to
 * agree.
 */
uint32_t usbdma_out_status(void)
{
	return UOTGHS->UOTGHS_DEVDMA[DMA_OUT_CH].UOTGHS_DEVDMASTATUS;
}

static bool dma_out_start_ctl(void *buf, uint32_t len, uint32_t extra)
{
	if (!mode_out || !usbdma_ready() || len == 0)
		return false;
	if (usbdma_out_busy())
		return false;

	UOTGHS->UOTGHS_DEVDMA[DMA_OUT_CH].UOTGHS_DEVDMAADDRESS = (uint32_t)buf;
	UOTGHS->UOTGHS_DEVDMA[DMA_OUT_CH].UOTGHS_DEVDMACONTROL =
		  UOTGHS_DEVDMACONTROL_BUFF_LENGTH(len)
		| extra
		| UOTGHS_DEVDMACONTROL_END_B_EN
		| UOTGHS_DEVDMACONTROL_END_BUFFIT
		| UOTGHS_DEVDMACONTROL_CHANN_ENB;
	usb_out_activity++;
	return true;
}

bool usbdma_out_start(void *buf, uint32_t len)
{
	/* END_TR_EN stops on a short packet, which is how a host signals
	 * the end of a transfer smaller than the buffer. Right for
	 * request/response traffic like the benches. */
	return dma_out_start_ctl(buf, len, UOTGHS_DEVDMACONTROL_END_TR_EN);
}

bool usbdma_out_start_stream(void *buf, uint32_t len)
{
	/*
	 * No END_TR_EN: a continuous sample stream never legitimately ends,
	 * and a short packet - which host-side pacing produces whenever a
	 * write is not a multiple of 512 - must not terminate the transfer.
	 * Ending it there forces a re-arm through the main loop every
	 * couple of kilobytes, and that re-arm latency was a measured
	 * throughput ceiling on Track B.
	 */
	return dma_out_start_ctl(buf, len, 0);
}

/* ------------------------------------------------------------------ */
/* IN: device -> host                                                  */
/* ------------------------------------------------------------------ */

bool usbdma_in_busy(void)
{
	return (UOTGHS->UOTGHS_DEVDMA[DMA_IN_CH].UOTGHS_DEVDMASTATUS
	        & UOTGHS_DEVDMASTATUS_CHANN_ENB) != 0;
}

uint32_t usbdma_in_residue(void)
{
	return (UOTGHS->UOTGHS_DEVDMA[DMA_IN_CH].UOTGHS_DEVDMASTATUS
	        & UOTGHS_DEVDMASTATUS_BUFF_COUNT_Msk)
	       >> UOTGHS_DEVDMASTATUS_BUFF_COUNT_Pos;
}

bool usbdma_in_start(const void *buf, uint32_t len)
{
	if (!mode_in || !usbdma_ready() || len == 0)
		return false;
	if (usbdma_in_busy())
		return false;

	UOTGHS->UOTGHS_DEVDMA[DMA_IN_CH].UOTGHS_DEVDMAADDRESS = (uint32_t)buf;
	UOTGHS->UOTGHS_DEVDMA[DMA_IN_CH].UOTGHS_DEVDMACONTROL =
		  UOTGHS_DEVDMACONTROL_BUFF_LENGTH(len)
		| UOTGHS_DEVDMACONTROL_END_B_EN
		| UOTGHS_DEVDMACONTROL_END_BUFFIT
		| UOTGHS_DEVDMACONTROL_CHANN_ENB;
	usb_in_activity++;
	return true;
}

void usbdma_dump(void)
{
	char buf[176];

	snprintf(buf, sizeof(buf),
	         "# usbdma mode in=%d out=%d rebuilds=%lu dtr=%d",
	         (int)mode_in, (int)mode_out,
	         (unsigned long)usbdma_rebuilds, (int)SerialUSB.dtr());
	Serial.println(buf);
	snprintf(buf, sizeof(buf),
	         "# ep%u(OUT) CFG=%08lx AUTOSW=%d  ep%u(IN) CFG=%08lx AUTOSW=%d  DEVIMR=%08lx",
	         (unsigned)CDC_RX,
	         (unsigned long)UOTGHS->UOTGHS_DEVEPTCFG[CDC_RX],
	         (int)!!(UOTGHS->UOTGHS_DEVEPTCFG[CDC_RX] & UOTGHS_DEVEPTCFG_AUTOSW),
	         (unsigned)CDC_TX,
	         (unsigned long)UOTGHS->UOTGHS_DEVEPTCFG[CDC_TX],
	         (int)!!(UOTGHS->UOTGHS_DEVEPTCFG[CDC_TX] & UOTGHS_DEVEPTCFG_AUTOSW),
	         (unsigned long)UOTGHS->UOTGHS_DEVIMR);
	Serial.println(buf);
	Serial.flush();
}
