"""The device-neutral seams the H7 backend uses in the shared daemon (docs/20): a device may bring its own rate policy, and a device
that declares `accepts_options` is passed a channel mask and options. A device that does neither must behave exactly as before -
that is the Due, so every test here has a control arm with the plain FakeDevice."""
import json

import pytest

import pacing
import daemon.device as devmod
import daemon.rates as ratemod
import daemon.server as servermod
import daemon.client as clientmod


class Policy:
    """A rate policy of another kind: periods of a 200 MHz base, refusing anything under 80 ticks (2.5 MS/s)."""
    RateError = ratemod.RateError

    def check_capture(self, hz, channels):
        period = round(200_000_000 / hz)
        if period < 80:
            raise ratemod.RateError(f"{hz} Hz is period {period}, under 80")
        return period, 200_000_000 / period

    def check_dac(self, hz):
        period = round(200_000_000 / hz)
        if period < 40:
            raise ratemod.RateError(f"{hz} Hz is period {period}, under 40")
        return period, 200_000_000 / period

    def describe(self):
        return {"base_hz": 200_000_000, "adc_min_period": 80, "dac_min_period": 40, "source": "test policy"}


class OtherRates(devmod.FakeDevice):
    rate_policy = Policy()


class Opts(devmod.FakeDevice):
    accepts_options = True

    def start(self, mode, *, dac_sps=None, adc_hz=None, channels=2, waveform=None, preset=None, channel_mask=None, options=None):
        self.seen = {"channel_mask": channel_mask, "options": options}
        return super().start(mode, dac_sps=dac_sps, adc_hz=adc_hz, channels=channels, waveform=waveform, preset=preset)


class Plain(devmod.FakeDevice):
    """Records what start() got, and would raise TypeError if the server passed anything it was not told to accept."""
    def start(self, mode, *, dac_sps=None, adc_hz=None, channels=2, waveform=None, preset=None):
        self.kw = {"channels": channels}
        return super().start(mode, dac_sps=dac_sps, adc_hz=adc_hz, channels=channels, waveform=waveform, preset=preset)


def serve(dev):
    srv = servermod.Server(dev, host="127.0.0.1", port=0).start()
    c = clientmod.Client("127.0.0.1", srv.port, timeout=pacing.QUICK).connect(); c.hello("control")
    return srv, c


def test_a_device_without_a_policy_gets_the_dues_unchanged():
    srv, c = serve(devmod.FakeDevice(pace=False))
    try:
        r = c.call("rate", adc_hz=200000, channels=2)
        assert r["adc"]["rc"] == ratemod.rc_for(200000) and r["adc"]["actual_hz"] == ratemod.hz_for(ratemod.rc_for(200000))
        assert c.call("caps")["rates"] == json.loads(json.dumps(ratemod.describe()))   # as it crosses the wire (int keys become strings)
    finally:
        c.close(); srv.stop()


def test_a_devices_own_policy_decides_rate_start_and_caps():
    srv, c = serve(OtherRates(pace=False))
    try:
        r = c.call("rate", adc_hz=2_000_000, channels=1); assert r["adc"] == {"requested": 2_000_000, "rc": 100, "actual_hz": 2_000_000.0}
        assert c.call("caps")["rates"]["source"] == "test policy"
        with pytest.raises(clientmod.Refused):
            c.call("rate", adc_hz=4_000_000, channels=1)                    # period 50, under the policy's 80
        s = c.call("start", mode="capture", adc_hz=2_000_000, channels=1); assert s["rates"]["adc"]["actual_hz"] == 2_000_000.0
        c.call("stop")
        with pytest.raises(clientmod.Refused):                               # 4 MS/s is period 50: under this policy's floor
            c.call("start", mode="capture", adc_hz=4_000_000, channels=1)
    finally:
        c.close(); srv.stop()


def test_options_and_channel_mask_reach_only_a_device_that_accepts_them():
    dev = Opts(pace=False); srv, c = serve(dev)
    try:
        c.call("start", mode="capture", adc_hz=200000, channels=2, channel_mask=2, options={"gain": 3}); c.call("stop")
        assert dev.seen == {"channel_mask": 2, "options": {"gain": 3}}
    finally:
        c.close(); srv.stop()
    dev = Plain(pace=False); srv, c = serve(dev)
    try:
        c.call("start", mode="capture", adc_hz=200000, channels=2, channel_mask=2, options={"gain": 3}); c.call("stop")
        assert dev.kw == {"channels": 2}                                     # a device that did not ask got a call it can take
    finally:
        c.close(); srv.stop()
