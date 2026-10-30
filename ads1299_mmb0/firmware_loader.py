"""Load ads1299evm-pdk.bin into the MMB0 C5509 USB bootloader.

Host-side loader for the TI MMB0 USB bootloader (VID 0451 / PID 9001).
The DSP image itself is TI proprietary — obtain it from the ADS1299EEGFE-PDK
and pass ``-f`` / ``ADS1299_FIRMWARE`` (this package does not ship it).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

import usb.core
import usb.util

from .usb_ids import BOOT_OUT_EP, BOOT_PID, BOOT_VID, STYX_PID, STYX_VID

ProgressCb = Callable[[float, str], None]

FIRMWARE_BASENAME = "ads1299evm-pdk.bin"

_FIRMWARE_HELP = (
    f"DSP firmware `{FIRMWARE_BASENAME}` is not bundled (TI proprietary). "
    "Download the ADS1299EEGFE-PDK from "
    "https://www.ti.com/tool/ADS1299EEGFE-PDK , extract "
    f"`fw/{FIRMWARE_BASENAME}`, then either:\n"
    f"  export ADS1299_FIRMWARE=/path/to/{FIRMWARE_BASENAME}\n"
    f"  ads1299-load -f /path/to/{FIRMWARE_BASENAME}\n"
    f"  or place `{FIRMWARE_BASENAME}` in the current directory."
)


def resolve_firmware(bin_path: str | Path | None = None) -> Path:
    """Locate ``ads1299evm-pdk.bin`` from an explicit path, env, or cwd."""
    if bin_path is not None:
        path = Path(bin_path).expanduser()
        if path.is_file():
            return path
        raise FileNotFoundError(f"{path}\n\n{_FIRMWARE_HELP}")

    env = os.environ.get("ADS1299_FIRMWARE")
    if env:
        path = Path(env).expanduser()
        if path.is_file():
            return path
        raise FileNotFoundError(f"{path} (from ADS1299_FIRMWARE)\n\n{_FIRMWARE_HELP}")

    candidates = [
        Path.cwd() / FIRMWARE_BASENAME,
        Path.home() / ".local/share/ads1299-mmb0" / FIRMWARE_BASENAME,
        # Private local checkout may keep a copy under vendor/ (not published).
        Path(__file__).resolve().parents[1] / "vendor" / FIRMWARE_BASENAME,
    ]
    for path in candidates:
        if path.is_file():
            return path

    raise FileNotFoundError(_FIRMWARE_HELP)


# Preferred path for CLI help / GUI defaults (may not exist until user supplies it).
DEFAULT_FIRMWARE = Path.cwd() / FIRMWARE_BASENAME


def find_device(vid: int, pid: int) -> usb.core.Device | None:
    return usb.core.find(idVendor=vid, idProduct=pid)


def load_firmware(
    bin_path: str | Path | None = None,
    *,
    timeout_ms: int = 5000,
    progress: ProgressCb | None = None,
) -> None:
    """Write the DSP image to bootloader bulk OUT endpoint 6."""
    path = resolve_firmware(bin_path)
    data = path.read_bytes()
    if progress:
        progress(0.0, f"Loading {path.name} ({len(data)} B)…")
    dev = find_device(BOOT_VID, BOOT_PID)
    if dev is None:
        raise RuntimeError(
            f"MMB0 bootloader not found (VID={BOOT_VID:#06x} PID={BOOT_PID:#06x}). "
            "Power the board and connect USB before loading."
        )

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except (NotImplementedError, usb.core.USBError):
        pass

    dev.set_configuration()
    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]
    usb.util.claim_interface(dev, intf.bInterfaceNumber)

    try:
        chunk = 4096
        sent = 0
        while sent < len(data):
            n = min(chunk, len(data) - sent)
            dev.write(BOOT_OUT_EP, data[sent : sent + n], timeout=timeout_ms)
            sent += n
            if progress:
                progress(sent / len(data), f"Firmware {sent}/{len(data)} B")
    finally:
        usb.util.release_interface(dev, intf.bInterfaceNumber)
        usb.util.dispose_resources(dev)
    if progress:
        progress(1.0, "Firmware write done")


def wait_for_styx(
    bin_path: str | Path | None = None,
    *,
    timeout_s: float = 30.0,
    poll_s: float = 0.4,
    progress: ProgressCb | None = None,
) -> usb.core.Device:
    """Load firmware if needed, then wait until USBStyx re-enumerates."""
    deadline = time.monotonic() + timeout_s
    # Resolve once up front so missing firmware fails fast (unless already on Styx).
    resolved: Path | None = None

    while time.monotonic() < deadline:
        styx = find_device(STYX_VID, STYX_PID)
        if styx is not None:
            if progress:
                progress(1.0, "USBStyx ready")
            return styx

        boot = find_device(BOOT_VID, BOOT_PID)
        if boot is not None:
            if resolved is None:
                resolved = resolve_firmware(bin_path)
            if progress:
                progress(0.05, "Bootloader found — writing image…")
            load_firmware(resolved, progress=progress)
            time.sleep(2.0)
            continue

        time.sleep(poll_s)

    raise TimeoutError(
        f"Timed out waiting for USBStyx ({STYX_VID:#06x}:{STYX_PID:#06x})"
    )
