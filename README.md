# ads1299-mmb0

Python host for the **TI ADS1299EEG-FE** daughterboard on the **MMB0** motherboard.
Talks to stock DSP firmware over **USBStyx** (9P/Styx on USB bulk) — no LabVIEW required.

> **Not affiliated with Texas Instruments.** TI trademarks and materials remain TI’s.
> This repository ships **only** newly written Python. It does **not** include TI
> firmware binaries, LabVIEW apps, or PDK sources.

## Requirements

- Python 3.10+
- libusb (`brew install libusb` on macOS)
- Hardware: MMB0 + ADS1299EEG-FE
- TI DSP image `ads1299evm-pdk.bin` (you obtain separately)

## Get the TI firmware (required)

1. Open [ADS1299EEGFE-PDK](https://www.ti.com/tool/ADS1299EEGFE-PDK) and download the PDK software (TI account / export controls may apply).
2. Install or extract the package on a machine you control.
3. Locate `fw/ads1299evm-pdk.bin` (C5509 image loaded into the MMB0 USB bootloader).
4. Point this library at that file — **do not commit it to a public repo**:

```bash
export ADS1299_FIRMWARE=/path/to/ads1299evm-pdk.bin
# or pass -f /path/to/ads1299evm-pdk.bin
# or copy ads1299evm-pdk.bin into your working directory
```

Optional TI packages (for DSP changes only, not required to run this host):

- [ADS1299EEGFEFW-C5509](https://www.ti.com/tool/ADS1299EEGFE-PDK) — firmware source (export-gated)
- [ADS1299EEGFESW-SOURCE](https://www.ti.com/tool/ADS1299EEGFE-PDK) — EVM software source (export-gated)

## Install

```bash
pip install -e ".[gui]"   # GUI optional; needs tkinter + matplotlib
# or: pip install -e ".[dev]"
```

## Quick start

```bash
ads1299-load --wait -f "$ADS1299_FIRMWARE"
ads1299-capture -n 64 -o out.bin --npy out.npy
ads1299-gui
ads1299-shell --no-load
```

```python
from ads1299_mmb0 import ADS1299
from ads1299_mmb0.stream import acquire_continuous

with ADS1299.open() as dev:  # uses ADS1299_FIRMWARE / cwd if board needs load
    print(dev.read_path("/version"))
    volts = dev.acquire(n_samples=64)  # (64, 8) float volts
    long = acquire_continuous(dev, total_frames=8192, chunk_frames=4096)
```

### USB IDs

| State | VID | PID |
|-------|-----|-----|
| Bootloader (before FW) | `0x0451` | `0x9001` |
| USBStyx (after FW) | `0x0451` | `0x5718` |

If USB bulk wedges after a failed acquire: power-cycle the MMB0 wall wart, wait for `0451:9001`, then load again.

### Continuous capture

Stock firmware is **buffer-then-USB** (~1 MB ≈ ~28k frames). This package offers **segmented** continuous capture (gaps between blocks are expected). True zero-gap streaming needs custom DSP firmware (out of scope).

## License

MIT for the Python code in this repository.

TI firmware, PDK installers, LabVIEW GUIs, and related sources remain under Texas Instruments’ terms — obtain and use them only as TI allows. This project is an independent host-side client for interoperability with the evaluation hardware.
