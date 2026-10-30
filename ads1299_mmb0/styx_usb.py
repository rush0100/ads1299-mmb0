"""USB bulk transport matching TI cstyx USBConnection."""

from __future__ import annotations

import usb.core
import usb.util

from .usb_ids import STYX_IN_EP, STYX_OUT_EP, STYX_PID, STYX_VID


class StyxUSBError(RuntimeError):
    pass


class StyxUSB:
    """Pad TX/RX to wMaxPacketSize with 0x01, as TI cstyx does."""

    def __init__(
        self,
        vid: int = STYX_VID,
        pid: int = STYX_PID,
        *,
        timeout_ms: int = 3000,
    ) -> None:
        self.timeout_ms = timeout_ms
        self._rxq = bytearray()
        self.dev = usb.core.find(idVendor=vid, idProduct=pid)
        if self.dev is None:
            raise StyxUSBError(f"USBStyx device not found ({vid:#06x}:{pid:#06x})")

        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except (NotImplementedError, usb.core.USBError):
            pass

        self.dev.set_configuration()
        cfg = self.dev.get_active_configuration()
        intf = cfg[(0, 0)]
        self._iface = intf.bInterfaceNumber
        usb.util.claim_interface(self.dev, self._iface)

        # Match TI: use first endpoint's wMaxPacketSize for bulk padding.
        eps = list(intf.endpoints())
        if not eps:
            raise StyxUSBError("USBStyx interface has no endpoints")
        self.pkt = int(eps[0].wMaxPacketSize)
        try:
            self.dev.clear_halt(STYX_IN_EP)
            self.dev.clear_halt(STYX_OUT_EP)
        except usb.core.USBError:
            pass

    def close(self) -> None:
        if self.dev is None:
            return
        try:
            usb.util.release_interface(self.dev, self._iface)
        except usb.core.USBError:
            pass
        usb.util.dispose_resources(self.dev)
        self.dev = None

    def __enter__(self) -> StyxUSB:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _round_up(self, n: int) -> int:
        return ((n // self.pkt) + 1) * self.pkt

    def flush(self) -> None:
        self._rxq.clear()

    def write(self, data: bytes) -> None:
        assert self.dev is not None
        need = self._round_up(len(data))
        buf = data + bytes([0x01]) * (need - len(data))
        wrote = self.dev.write(STYX_OUT_EP, buf, timeout=self.timeout_ms)
        if wrote < 0:
            raise StyxUSBError("usb transmit error")

    def read(self, n: int) -> bytes:
        assert self.dev is not None
        while len(self._rxq) < n:
            act = self._round_up(n - len(self._rxq))
            chunk = self.dev.read(STYX_IN_EP, act, timeout=self.timeout_ms)
            self._rxq.extend(bytes(chunk))
        out = bytes(self._rxq[:n])
        del self._rxq[:n]
        return out
