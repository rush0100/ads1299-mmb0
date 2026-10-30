# ads1299-mmb0

[![CI](https://github.com/rush0100/ads1299-mmb0/actions/workflows/ci.yml/badge.svg)](https://github.com/rush0100/ads1299-mmb0/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

Python host for the **TI ADS1299EEG-FE** daughterboard on the **MMB0** motherboard.
Talks to stock DSP firmware over **USBStyx** (9P/Styx on USB bulk) — no LabVIEW required.

> **Not affiliated with Texas Instruments.** TI trademarks and materials remain TI’s.
> This repository ships **only** newly written Python. It does **not** include TI
> firmware binaries, LabVIEW apps, or PDK sources. See [NOTICE](NOTICE).

## Features

- Load `ads1299evm-pdk.bin` into the MMB0 USB bootloader
- Styx client over USB bulk (registers, acquire, `/data`)
- One-shot and segmented continuous capture → NumPy
- CLI tools + optional evaluation GUI
- No bundled proprietary firmware

## Requirements

| Item | Notes |
|------|--------|
| Python | 3.10+ |
| libusb | macOS: `brew install libusb` |
| Hardware | MMB0 + ADS1299EEG-FE |
| Firmware | TI `ads1299evm-pdk.bin` (obtain separately) |

## Get the TI firmware (required)

1. Open [ADS1299EEGFE-PDK](https://www.ti.com/tool/ADS1299EEGFE-PDK) and download the PDK software (TI account / export controls may apply).
2. Install or extract the package on a machine you control.
3. Locate `fw/ads1299evm-pdk.bin` (C5509 image for the MMB0 USB bootloader).
4. Point this library at that file — **do not commit it**:

```bash
export ADS1299_FIRMWARE=/path/to/ads1299evm-pdk.bin
# or: ads1299-load -f /path/to/ads1299evm-pdk.bin
# or: place ads1299evm-pdk.bin in the current working directory
```

Optional TI packages (DSP development only; not required to run this host):

- Firmware source / software source linked from the same PDK page (often export-gated)

## Install

```bash
pip install git+https://github.com/rush0100/ads1299-mmb0.git
# development:
git clone https://github.com/rush0100/ads1299-mmb0.git
cd ads1299-mmb0
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,gui]"   # gui needs tkinter + matplotlib
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

with ADS1299.open() as dev:  # uses ADS1299_FIRMWARE / cwd when load is needed
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

## Documentation

| Doc | Purpose |
|-----|---------|
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup & PRs |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Community norms |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [NOTICE](NOTICE) | Trademark / third-party notice |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and features use GitHub issue templates.

## License

MIT for the Python code in this repository — see [LICENSE](LICENSE).

TI firmware, PDK installers, LabVIEW GUIs, and related sources remain under Texas Instruments’ terms. Obtain and use them only as TI allows. This project is an independent host-side client for interoperability with the evaluation hardware.
