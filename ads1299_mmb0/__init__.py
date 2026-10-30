"""Python client for TI ADS1299EEG-FE on the MMB0 motherboard."""

from .device import ADS1299
from .usb_ids import BOOT_PID, BOOT_VID, STYX_PID, STYX_VID

__all__ = [
    "ADS1299",
    "BOOT_VID",
    "BOOT_PID",
    "STYX_VID",
    "STYX_PID",
]
__version__ = "0.1.0"
