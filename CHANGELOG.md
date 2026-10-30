# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-30

### Added

- USBStyx (9P) host client for ADS1299EEG-FE on MMB0
- Firmware loader for `ads1299evm-pdk.bin` (path via `-f` / `ADS1299_FIRMWARE`)
- CLI: `ads1299-load`, `ads1299-shell`, `ads1299-capture`, `ads1299-gui`
- Block and segmented continuous capture APIs
- Optional matplotlib/tkinter evaluation GUI
- Register helpers, analysis presets, and unit tests

[Unreleased]: https://github.com/rush0100/ads1299-mmb0/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/rush0100/ads1299-mmb0/releases/tag/v0.1.0
