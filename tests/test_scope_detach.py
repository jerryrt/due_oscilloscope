"""UsbTmc detaches Linux's usbtmc driver before it claims the interface.

Without that libusb fails the claim with "Resource busy" on a Linux host,
where the kernel binds its own usbtmc driver to the instrument. Board-free:
a fake device stands in for pyusb's.
"""

import pytest

pytest.importorskip("usb.core")

import scope  # noqa: E402


class _Ep:
    def __init__(self, addr):
        self.bEndpointAddress = addr


class _Dev:
    def __init__(self, bound, raises=None):
        self.bound, self.raises, self.detached = bound, raises, False

    def is_kernel_driver_active(self, itf):
        if self.raises:
            raise self.raises
        return self.bound

    def detach_kernel_driver(self, itf):
        self.detached = True

    def set_configuration(self):
        pass

    def get_active_configuration(self):
        return {(0, 0): [_Ep(0x01), _Ep(0x81)]}


def _open(dev, monkeypatch):
    import usb.util
    monkeypatch.setattr(usb.util, "find_descriptor",
                        lambda itf, custom_match: next(
                            e for e in itf if custom_match(e)))
    return scope.UsbTmc(dev)


def test_a_bound_kernel_driver_is_detached(monkeypatch):
    dev = _Dev(bound=True)
    _open(dev, monkeypatch)
    assert dev.detached


def test_an_unbound_interface_is_left_alone(monkeypatch):
    dev = _Dev(bound=False)
    _open(dev, monkeypatch)
    assert not dev.detached


def test_a_platform_without_the_call_still_opens(monkeypatch):
    dev = _Dev(bound=False, raises=NotImplementedError())
    _open(dev, monkeypatch)
