"""
Domain 4: USB transport.

Slow, so it runs last. These benchmarks move data with no ADC, no DAC
and no ring involved, which is what makes them the reference the other
domains are read against: if the loop is short of rate and the transport
is at its usual figure, the transport is not the reason.

Tolerances are floors rather than bands, and they sit well below the
typical figure on purpose. Five 4 s runs per mode measured in-dma at
19.8-30.5, out-dma at 17.9-28.2 and duplex-dma at 8.2-20.0 MB/s: a
run-to-run spread of 35 to 59%, not the ~5% this project's notes
previously recorded. A floor near the typical figure would be a flaky
test rather than a strict one. What these have to catch is a collapse -
the ~1.7 MB/s gated-OUT regime that once blocked full-rate duplex - and
they still catch it by a factor of three or more.
"""

import pytest

import measure
from helpers import record, window

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("mode", ["in-dma", "out-dma", "duplex-dma"])
def test_endpoint_dma_throughput(board, baseline, calibration, seconds, mode):
    """What the host actually clocked, not what the device counted.

    The device cannot time its own benchmark: opening the control port
    resets it, so its window start is unrelated to when the host began
    measuring. It reports byte counts only, and the host keeps the
    clock.
    """
    secs = window(seconds, 4.0)
    res = measure.run_bench(board, mode=mode, seconds=secs)

    floor = baseline["transport_min_mbs"][mode]
    got = (res.rx_mbs + res.tx_mbs) if res.want_rx and res.want_tx else (
        res.rx_mbs if res.want_rx else res.tx_mbs)
    record(calibration, f"transport_{mode}", {
        "rx_mbs": round(res.rx_mbs, 3), "tx_mbs": round(res.tx_mbs, 3),
        "combined_mbs": round(got, 3)})
    assert got >= floor, (
        f"{mode} moved {got:.2f} MB/s against a {floor} MB/s floor")


@pytest.mark.parametrize("mode", ["in-dma", "out-dma"])
def test_device_agrees_with_the_host_on_the_byte_count(board, seconds, mode):
    """A large disagreement means one side is not seeing what the other
    sent, which is the difference between a slow link and a lossy one.

    The device is stopped asynchronously, so it has always counted more
    than the host measured in its window; what is checked is the order
    of magnitude, not equality.
    """
    secs = window(seconds, 4.0)
    res = measure.run_bench(board, mode=mode, seconds=secs)

    host = res.host_rx_bytes if res.want_rx else res.host_tx_bytes
    dev = res.device.in_bytes if res.want_rx else res.device.out_bytes
    assert host > 0, f"the host moved nothing in {mode}"
    assert dev > 0, f"the device counted nothing in {mode}\n{res.report}"
    assert dev >= host * 0.5, (
        f"{mode}: the device counted {dev} bytes against the host's {host}; "
        f"one side is missing more than half of what the other saw")


def test_dma_channels_were_actually_used(board, seconds):
    """The DMA benchmarks must arm DMA.

    A silent fallback to the CPU FIFO path would still move data and
    still report a rate, just a different one, and the invariant that
    the CPU never touches the sample stream would be broken with nothing
    to show for it.
    """
    res = measure.run_bench(board, mode="in-dma", seconds=window(seconds, 3.0))
    arms = res.device.arms_in
    assert arms, f"in-dma armed no IN DMA transfers\n{res.report}"
    assert res.device.mode == "flood-dma", (
        f"device reports bench mode {res.device.mode!r}, not flood-dma")
