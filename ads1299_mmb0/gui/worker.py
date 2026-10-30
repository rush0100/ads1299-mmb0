"""Device operations used by the GUI (run off the Tk main thread)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ads1299_mmb0 import data as data_mod
from ads1299_mmb0.device import ADS1299
from ads1299_mmb0.firmware_loader import find_device, wait_for_styx
from ads1299_mmb0.presets import PRESETS
from ads1299_mmb0.registers import REGS
from ads1299_mmb0.stream import DEFAULT_CHUNK_FRAMES, StreamBlock, iter_blocks
from ads1299_mmb0.usb_ids import BOOT_PID, BOOT_VID, STYX_PID, STYX_VID


class DeviceSession:
    def __init__(self) -> None:
        self.dev: ADS1299 | None = None
        self.firmware: str | None = None  # ADS1299_FIRMWARE / cwd / -f equivalent
        self.vref = 4.5
        self.gain = 24.0
        self.last_volts: np.ndarray | None = None
        self.last_codes: np.ndarray | None = None
        self.last_raw: bytes | None = None
        self.last_sps: float = 250.0
        self.last_regs: dict[str, int] = {}
        self.progress_text: str = ""
        self.progress_frac: float = 0.0
        self.stream_stop = threading.Event()
        self.stream_frames: int = 0
        self.stream_blocks: int = 0
        self.stream_last_gap_ms: float = 0.0
        self.rolling_volts: np.ndarray | None = None
        self._rolling_max = 1024

    @property
    def connected(self) -> bool:
        return self.dev is not None

    def usb_status(self) -> str:
        boot = find_device(BOOT_VID, BOOT_PID) is not None
        styx = find_device(STYX_VID, STYX_PID) is not None
        return f"boot={'yes' if boot else 'no'}  styx={'yes' if styx else 'no'}"

    def _on_progress(self, frac: float, msg: str) -> None:
        self.progress_frac = float(frac)
        self.progress_text = msg

    def connect(self) -> str:
        self.disconnect()
        boot = find_device(BOOT_VID, BOOT_PID) is not None
        styx = find_device(STYX_VID, STYX_PID) is not None
        if not boot and not styx:
            raise RuntimeError("MMB0 not found. Power the board and connect USB.")
        self._on_progress(0.0, "Connecting…")
        wait_for_styx(self.firmware, timeout_s=30, progress=self._on_progress)
        time.sleep(0.5)
        self.dev = ADS1299.open(load_fw=False, firmware=self.firmware, timeout_s=5)
        self.dev.ensure_capture_defaults()
        ver = self.dev.read_path("/version")
        ident = self.dev.read_path("/id")
        devid = self.dev.read_path("/ads1299evm/conf/devid")
        eeprom = self.read_eeprom_info()
        self._on_progress(1.0, "Connected")
        extra = f"  eeprom={eeprom}" if eeprom else ""
        return f"{ident}  fw={ver}  ID={devid}  ({self.usb_status()}){extra}"

    def disconnect(self) -> None:
        if self.dev is not None:
            try:
                self.dev.close()
            except Exception:
                pass
            self.dev = None

    def _require(self) -> ADS1299:
        if self.dev is None:
            raise RuntimeError("Not connected")
        return self.dev

    def read_path(self, path: str) -> str:
        return self._require().read_path(path)

    def write_path(self, path: str, value: str) -> int:
        return self._require().write_path(path, value)

    def read_eeprom_info(self) -> str:
        """Best-effort EEPROM / board identity strings."""
        dev = self._require()
        parts: list[str] = []
        for p in ("/eprom/name", "/mmb0/eprom/name", "/id"):
            try:
                t = dev.read_path(p).strip()
                if t:
                    parts.append(t)
                    break
            except Exception:
                continue
        return " ".join(parts)

    def read_all_registers(self) -> dict[str, int]:
        dev = self._require()
        out: dict[str, int] = {}
        for reg in REGS:
            out[reg.styx] = dev.read_register(reg)
        self.last_regs = dict(out)
        return out

    def write_register(self, styx: str, value: int) -> None:
        dev = self._require()
        if styx in {"reset", "sleep"}:
            dev.write_path(f"{dev.CONF}/{styx}", str(int(value) & 0xFF))
        else:
            dev.write_register(styx, value)

    def apply_preset(self, key: str) -> str:
        preset = PRESETS[key]
        for styx, val in preset.regs.items():
            self.write_register(styx, val)
        self.read_all_registers()
        return f"Applied preset: {preset.name}. {preset.note}"

    def poll_lead_off(self) -> tuple[int, int]:
        """Return (loffstatp, loffstatn)."""
        regs = self.read_all_registers()
        return regs.get("loffstatp", 0), regs.get("loffstatn", 0)

    def capture(self, n_samples: int) -> tuple[np.ndarray | None, np.ndarray | None, str]:
        """Capture ``n_samples`` EEG frames (FW ``blocksize = n×9`` int32 words)."""
        dev = self._require()
        n_samples = max(1, int(n_samples))
        self.vref = float(self.vref)
        self.gain = float(self.gain)
        sps = max(dev.sample_rate_sps(), 1.0)
        self.last_sps = sps
        timeout_s = max(5.0, n_samples / sps * 4.0 + 2.0)
        raw = dev.acquire_raw(
            n_samples=n_samples,
            ensure_defaults=False,
            arm_data=False,
            timeout_s=timeout_s,
        )
        if not raw:
            self.last_volts = None
            self.last_codes = None
            self.last_raw = None
            return (
                None,
                None,
                "No data from /ads1299evm/data. Power-cycle wall wart if USB wedged.",
            )
        if len(raw) % data_mod.BYTES_PER_FRAME == 0:
            _, codes = data_mod.decode_styx_i32_be(raw)
        elif len(raw) % data_mod.SPI_FRAME == 0:
            _, codes = data_mod.decode_spi_frames(raw)
        else:
            try:
                codes = data_mod.decode_i32_le(raw)
            except ValueError as e:
                self.last_volts = None
                self.last_codes = None
                return None, None, f"Undecodable buffer ({len(raw)} B): {e}"
        volts = data_mod.codes_to_volts(codes, vref=self.vref, gain=self.gain)
        self.last_codes = codes
        self.last_volts = volts
        self.last_raw = raw
        try:
            self.last_regs = self.read_all_registers()
        except Exception:
            pass
        return (
            volts,
            codes,
            f"{codes.shape[0]} frames × {codes.shape[1]} ch ({len(raw)} B @ {sps:.0f} SPS)",
        )

    def _append_rolling(self, volts: np.ndarray) -> None:
        if self.rolling_volts is None or self.rolling_volts.size == 0:
            self.rolling_volts = volts[-self._rolling_max :]
            return
        self.rolling_volts = np.concatenate([self.rolling_volts, volts], axis=0)[
            -self._rolling_max :
        ]

    def run_continuous(
        self,
        *,
        chunk_frames: int = DEFAULT_CHUNK_FRAMES,
        duration_s: float | None = None,
        on_block: Callable[[StreamBlock], None] | None = None,
    ) -> str:
        """Segmented continuous capture until stop_event or duration.

        Call ``stream_stop.clear()`` before start; ``stream_stop.set()`` to stop.
        """
        dev = self._require()
        self.vref = float(self.vref)
        self.gain = float(self.gain)
        self.last_sps = max(dev.sample_rate_sps(), 1.0)
        self.stream_stop.clear()
        self.stream_frames = 0
        self.stream_blocks = 0
        self.stream_last_gap_ms = 0.0
        self.rolling_volts = None
        chunks_v: list[np.ndarray] = []
        chunks_c: list[np.ndarray] = []

        for block in iter_blocks(
            dev,
            chunk_frames=chunk_frames,
            duration_s=duration_s,
            stop_event=self.stream_stop,
            vref=self.vref,
            gain=self.gain,
        ):
            chunks_v.append(block.volts)
            chunks_c.append(block.codes)
            self.stream_frames += block.volts.shape[0]
            self.stream_blocks += 1
            self.stream_last_gap_ms = block.gap_s * 1000.0
            self._append_rolling(block.volts)
            if on_block:
                on_block(block)

        if chunks_v:
            self.last_volts = np.concatenate(chunks_v, axis=0)
            self.last_codes = np.concatenate(chunks_c, axis=0)
        msg = (
            f"Continuous done: {self.stream_frames} frames in {self.stream_blocks} blocks "
            f"(segmented; last gap {self.stream_last_gap_ms:.1f} ms)"
        )
        return msg

    def save_bundle(
        self,
        directory: str | Path,
        *,
        notes: str = "",
        channels: list[bool] | None = None,
        stem: str | None = None,
    ) -> str:
        """Write csv + npy + meta.json into DataDir."""
        if self.last_volts is None or self.last_codes is None:
            raise RuntimeError("No capture yet")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stem = stem or datetime.now(timezone.utc).strftime("ads1299_%Y%m%d_%H%M%S")
        ch_mask = channels or [True] * self.last_volts.shape[1]
        idx = [i for i, on in enumerate(ch_mask) if on]
        if not idx:
            raise RuntimeError("Select at least one channel")
        volts = self.last_volts[:, idx]
        codes = self.last_codes[:, idx]
        csv_path = directory / f"{stem}.csv"
        npy_path = directory / f"{stem}_codes.npy"
        meta_path = directory / f"{stem}_meta.json"
        with csv_path.open("w", newline="") as f:
            import csv

            w = csv.writer(f)
            w.writerow(["sample"] + [f"ch{i+1}" for i in idx])
            for i, row in enumerate(volts):
                w.writerow([i, *[f"{v:.10e}" for v in row]])
        np.save(npy_path, codes)
        meta = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
            "frames": int(volts.shape[0]),
            "channels": [i + 1 for i in idx],
            "vref": self.vref,
            "gain": self.gain,
            "sps": self.last_sps,
            "registers": {k: f"0x{v:02X}" for k, v in self.last_regs.items()},
            "raw_bytes": len(self.last_raw or b""),
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return str(directory / stem)
