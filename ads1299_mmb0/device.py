"""High-level ADS1299EEG-FE API over USBStyx."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import usb.core

from . import data as data_mod
from .firmware_loader import wait_for_styx
from .registers import BY_NAME, BY_STYX, Reg
from .styx_client import TI_ORDWR, StyxClient, StyxError
from .styx_usb import StyxUSB

_USB_TIMEOUTS: tuple[type[BaseException], ...] = (usb.core.USBError,)
if hasattr(usb.core, "USBTimeoutError"):
    _USB_TIMEOUTS = (usb.core.USBTimeoutError, usb.core.USBError)

# CONFIG1 DR[2:0] → samples/s (ADS1299 datasheet / EVM map).
_DR_SPS = {
    0b000: 16_000,
    0b001: 8_000,
    0b010: 4_000,
    0b011: 2_000,
    0b100: 1_000,
    0b101: 500,
    0b110: 250,
    # 0b111 reserved on ADS1299 — falls back to 250
}

# Live board (ads1299evm-pdk 0.0.27):
#   blocksize_samples = N_words (must be multiple of 9 = status+8ch)
#   /data length = 4 * N_words = 36 * N_frames
# User-facing n_samples = EEG frames → blocksize = n_samples * 9.
_WORDS_PER_FRAME = 9
_BYTES_PER_FRAME = 36
_DEFAULT_FRAMES = 64  # → blocksize 576 (known-good)


class ADS1299:
    CONF = "/ads1299evm/conf"
    DATA = "/ads1299evm/data"

    def __init__(self, client: StyxClient) -> None:
        self.client = client
        # LabVIEW keeps a cstyx File* on /ads1299evm/data for the whole session.
        self._data_fid: int | None = None

    @classmethod
    def open(
        cls,
        *,
        load_fw: bool = True,
        firmware: str | Path | None = None,
        timeout_s: float = 30.0,
    ) -> ADS1299:
        if load_fw:
            wait_for_styx(firmware, timeout_s=timeout_s)
        transport = StyxUSB()
        client = StyxClient(transport)
        dev = cls(client)
        try:
            dev._open_data_fid()
        except Exception:
            # Still usable for register I/O; acquire_raw will retry the open.
            pass
        return dev

    def close(self) -> None:
        try:
            self._close_data_fid()
        except Exception:
            self._data_fid = None
        try:
            self.client.close()
        except Exception:
            pass

    def __enter__(self) -> ADS1299:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _open_data_fid(self) -> int:
        if self._data_fid is not None:
            return self._data_fid
        # LabVIEW Main.vi write_path's /data — open RDWR (TI 0666 → 0xB6).
        self._data_fid = self.client.open_fid(self.DATA, TI_ORDWR)
        return self._data_fid

    def _close_data_fid(self) -> None:
        fid = self._data_fid
        self._data_fid = None
        if fid is not None:
            self.client.clunk(fid)

    def read_path(self, path: str) -> str:
        return self.client.read_text(path)

    def write_path(self, path: str, value: str | bytes) -> int:
        return self.client.write_all(path, value)

    def _resolve(self, name: str | Reg) -> Reg:
        if isinstance(name, Reg):
            return name
        key = name.lower()
        if key in BY_NAME:
            return BY_NAME[key]
        if key in BY_STYX:
            return BY_STYX[key]
        raise KeyError(name)

    def read_register(self, name: str | Reg) -> int:
        reg = self._resolve(name)
        text = self.read_path(f"{self.CONF}/{reg.styx}").strip().lower()
        # Firmware returns values like "0x96"; int(..., 0) honors the 0x prefix.
        return int(text, 0)

    def write_register(self, name: str | Reg, value: int) -> None:
        reg = self._resolve(name)
        # Prefer 0xNN — verified on hardware ("0x96" stores 0x96; bare "96" stores 96).
        self.write_path(f"{self.CONF}/{reg.styx}", f"{value & 0xFF:#04x}")

    def reset(self) -> None:
        self.write_path(f"{self.CONF}/reset", "1")

    def set_blocksize(self, samples: int) -> None:
        """Write ``/ads1299evm/blocksize_samples`` (int32 **word** count)."""
        self.write_path("/ads1299evm/blocksize_samples", str(int(samples)))

    def set_blocksize_frames(self, n_frames: int) -> None:
        """Request ``n_frames`` EEG samples (writes word count ``n_frames * 9``)."""
        n_frames = int(n_frames)
        if n_frames < 1:
            raise ValueError("n_frames must be >= 1")
        self.set_blocksize(n_frames * _WORDS_PER_FRAME)

    def sample_rate_sps(self) -> float:
        try:
            cfg1 = self.read_register("config1")
        except Exception:
            return 250.0
        return float(_DR_SPS.get(cfg1 & 0x7, 250))

    @staticmethod
    def _acquire_is_idle(text: str) -> bool:
        t = text.strip().lower().replace("0x", "")
        if not t:
            return True
        try:
            return int(t, 16 if any(c in t for c in "abcdef") else 10) == 0
        except ValueError:
            return t in {"0", "false", "off"}

    def _stop_acquire(self) -> None:
        try:
            self.write_path("/ads1299evm/acquire", "0")
        except Exception:
            pass

    def ensure_capture_defaults(self) -> None:
        """Bring-up bits LabVIEW/EVM rely on before acquire."""
        try:
            # MMB0 DSP clock: 12 MHz, PLL off (common EVM default).
            # /mmb0/clkout is a frequency (Hz), not a boolean — leave unless known.
            self.write_path("/mmb0/clkfreq", "12000000")
            self.write_path("/mmb0/pll", "0")
        except Exception:
            pass
        try:
            cfg3 = self.read_register("config3")
        except Exception:
            return
        if cfg3 & 0x80:
            return
        # Match common EVM bring-up: refbuf + biasref_int on.
        self.write_register("config3", cfg3 | 0xE0)

    def acquire_raw(
        self,
        *,
        n_samples: int = _DEFAULT_FRAMES,
        settle_s: float | None = None,
        timeout_s: float | None = None,
        ensure_defaults: bool = True,
        arm_data: bool = False,
    ) -> bytes:
        """Capture ``n_samples`` EEG frames from ``/ads1299evm/data``.

        Live ``ads1299evm-pdk`` 0.0.27 (verified):

        * ``blocksize_samples = n_samples * 9`` (int32 words: status+8ch).
        * ``acquire=1`` with **no** ``/data`` arm write.
        * Do **not** poll ``/acquire`` in the fill loop (wedges USB).
        * DSP self-clears ``acquire`` when full; payload = ``36 * n_samples`` B
          (BE int32 × 9 per frame).
        * Word counts not divisible by 9 (e.g. raw 256) hang the DSP.
        """
        n_samples = int(n_samples)
        if n_samples < 1:
            raise ValueError("n_samples must be >= 1")

        if ensure_defaults:
            self.ensure_capture_defaults()

        sps = self.sample_rate_sps()
        if timeout_s is None:
            timeout_s = max(3.0, n_samples / max(sps, 1.0) * 3.0 + 2.0)
        if settle_s:
            timeout_s += float(settle_s)

        need = _BYTES_PER_FRAME * n_samples
        words = n_samples * _WORDS_PER_FRAME

        transport = self.client.t
        old_timeout = transport.timeout_ms
        transport.timeout_ms = max(old_timeout, int(min(timeout_s, 15.0) * 1000) + 500)

        self._stop_acquire()
        time.sleep(0.05)
        self.set_blocksize(words)

        raw = b""
        try:
            try:
                fid = self._open_data_fid()
            except Exception:
                self._close_data_fid()
                fid = self._open_data_fid()

            if arm_data:
                try:
                    self.client.write_fid(fid, b"0")
                except (StyxError, OSError, *_USB_TIMEOUTS):
                    pass

            self.write_path("/ads1299evm/acquire", "1")

            deadline = time.monotonic() + float(timeout_s)
            off = 0
            empty_streak = 0
            while time.monotonic() < deadline and off < need:
                try:
                    chunk = self.client.read_fid(
                        fid, off + 1024, offset=off, chunk=1024
                    )
                except _USB_TIMEOUTS as e:
                    if "timeout" not in str(e).lower() and "timed out" not in str(e).lower():
                        if getattr(e, "errno", None) not in {60, 110}:
                            raise
                    chunk = b""
                except StyxError:
                    raise
                if chunk:
                    raw += chunk
                    off += len(chunk)
                    empty_streak = 0
                    if off >= need:
                        break
                    continue
                empty_streak += 1
                if empty_streak == 10 and off > 0:
                    try:
                        if self._acquire_is_idle(self.read_path("/ads1299evm/acquire")):
                            break
                    except Exception:
                        pass
                time.sleep(0.02)
        finally:
            try:
                self._stop_acquire()
            except Exception:
                pass
            transport.timeout_ms = old_timeout

        return raw

    def acquire(
        self,
        *,
        n_samples: int = _DEFAULT_FRAMES,
        vref: float = 4.5,
        gain: float = 24.0,
        as_volts: bool = True,
    ) -> np.ndarray:
        raw = self.acquire_raw(n_samples=n_samples)
        if not raw:
            return np.zeros((0, data_mod.N_CH), dtype=np.float64 if as_volts else np.int32)
        if len(raw) % data_mod.BYTES_PER_FRAME == 0 and len(raw) >= data_mod.BYTES_PER_FRAME:
            _, codes = data_mod.decode_styx_i32_be(raw)
        elif len(raw) % data_mod.SPI_FRAME == 0 and len(raw) >= data_mod.SPI_FRAME:
            _, codes = data_mod.decode_spi_frames(raw)
        else:
            codes = data_mod.decode_i32_le(raw)
        if as_volts:
            return data_mod.codes_to_volts(codes, vref=vref, gain=gain)
        return codes
