# Contributing

Thanks for helping improve `ads1299-mmb0`.

## Ground rules

- Do **not** commit TI proprietary files: firmware (`.bin`), PDK installers, LabVIEW apps, or extracted vendor trees.
- Keep changes focused; open an issue first for large features.
- Follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

```bash
git clone https://github.com/rush0100/ads1299-mmb0.git
cd ads1299-mmb0
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,gui]"
pytest
```

Hardware tests need an MMB0 + ADS1299EEG-FE and `ADS1299_FIRMWARE` pointing at TI’s `ads1299evm-pdk.bin`. Unit tests in CI do not require hardware.

## Pull requests

1. Fork and create a branch from `main`.
2. Add or update tests when behavior changes.
3. Run `pytest` locally.
4. Open a PR with a short description of *why* the change exists.

## Reporting bugs

Use the bug report issue template. Include OS, Python version, USB IDs seen (`0451:9001` / `0451:5718`), and whether firmware load succeeded — never paste proprietary firmware blobs.
