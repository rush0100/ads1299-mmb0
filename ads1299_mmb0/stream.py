"""Segmented continuous capture beyond a single MMB0 onboard buffer.

Stock ads1299evm-pdk fills RAM then USB-transfers (TI ~1 MB). True zero-gap
USB streaming needs custom DSP firmware. This module loops ``acquire_raw``
in chunks ≤ the buffer and stitches results, recording inter-block gaps.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np

from . import data as data_mod
from .device import ADS1299

# TI E2E: ~1 MB onboard. 36 B/frame → theoretical max ~29127 frames.
MAX_BUFFER_BYTES = 1_000_000
MAX_FRAMES_THEORETICAL = MAX_BUFFER_BYTES // data_mod.BYTES_PER_FRAME  # 27777
# Default chunk: power-of-two friendly, well under the 1 MB ceiling.
DEFAULT_CHUNK_FRAMES = 4096
# Conservative upper bound used unless probe_max_frames says otherwise.
SAFE_MAX_FRAMES = 8192


@dataclass
class StreamBlock:
    volts: np.ndarray  # (N, 8)
    codes: np.ndarray  # (N, 8)
    gap_s: float  # time since previous block ended (0 for first)
    t_mono: float  # time.monotonic() when block read finished
    chunk_index: int


@dataclass
class ContinuousResult:
    volts: np.ndarray
    codes: np.ndarray
    gaps_s: list[float] = field(default_factory=list)
    chunk_frames: int = 0
    sps: float = 250.0
    n_blocks: int = 0


def clamp_chunk_frames(chunk_frames: int, *, hard_max: int = SAFE_MAX_FRAMES) -> int:
    n = int(chunk_frames)
    if n < 1:
        raise ValueError("chunk_frames must be >= 1")
    return min(n, hard_max, MAX_FRAMES_THEORETICAL)


def probe_max_frames(
    dev: ADS1299,
    *,
    lo: int = 64,
    hi: int = SAFE_MAX_FRAMES,
    vref: float = 4.5,
    gain: float = 24.0,
) -> int:
    """Binary-search largest chunk that returns a full buffer (live board).

    On failure/hang risk the caller should power-cycle. Uses ensure_defaults=False.
    """
    lo = max(1, int(lo))
    hi = clamp_chunk_frames(hi)
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        # Align down to multiple of 8 for slightly nicer sizes (not required by FW).
        mid = max(1, mid)
        try:
            raw = dev.acquire_raw(
                n_samples=mid, ensure_defaults=False, arm_data=False
            )
        except Exception:
            hi = mid - 1
            continue
        need = data_mod.BYTES_PER_FRAME * mid
        if raw and len(raw) >= need:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
        time.sleep(0.05)
    return best


def _decode_block(
    raw: bytes, *, vref: float, gain: float
) -> tuple[np.ndarray, np.ndarray]:
    if not raw:
        raise RuntimeError("empty block from /data")
    if len(raw) % data_mod.BYTES_PER_FRAME == 0:
        _, codes = data_mod.decode_styx_i32_be(raw)
    elif len(raw) % data_mod.SPI_FRAME == 0:
        _, codes = data_mod.decode_spi_frames(raw)
    else:
        codes = data_mod.decode_i32_le(raw)
    volts = data_mod.codes_to_volts(codes, vref=vref, gain=gain)
    return volts, codes


def iter_blocks(
    dev: ADS1299,
    *,
    chunk_frames: int = DEFAULT_CHUNK_FRAMES,
    duration_s: float | None = None,
    total_frames: int | None = None,
    stop_event: threading.Event | None = None,
    vref: float = 4.5,
    gain: float = 24.0,
    inter_block_pause_s: float = 0.05,
) -> Iterator[StreamBlock]:
    """Yield successive capture blocks until duration, frame budget, or stop.

    ``gap_s`` is wall time between end of previous block read and end of this
    one, minus the nominal fill time ``chunk_frames/sps`` (clamped ≥ 0) is
    *not* subtracted — raw inter-completion gap is reported so callers see
    total dead time including USB. First block has ``gap_s=0``.
    """
    chunk = clamp_chunk_frames(chunk_frames)
    if duration_s is None and total_frames is None and stop_event is None:
        raise ValueError("pass duration_s, total_frames, and/or stop_event")

    deadline = (
        time.monotonic() + float(duration_s) if duration_s is not None else None
    )
    frames_left = int(total_frames) if total_frames is not None else None
    prev_end: float | None = None
    idx = 0

    while True:
        if stop_event is not None and stop_event.is_set():
            break
        if deadline is not None and time.monotonic() >= deadline:
            break
        n = chunk
        if frames_left is not None:
            if frames_left <= 0:
                break
            n = min(chunk, frames_left)

        raw = dev.acquire_raw(n_samples=n, ensure_defaults=False, arm_data=False)
        t_end = time.monotonic()
        if not raw:
            raise RuntimeError(
                f"continuous stream: empty block #{idx} (n={n}); "
                "power-cycle if USB wedged"
            )
        volts, codes = _decode_block(raw, vref=vref, gain=gain)
        # Truncate if DSP returned fewer frames than requested
        if volts.shape[0] < n:
            n = volts.shape[0]
        gap = 0.0 if prev_end is None else max(0.0, t_end - prev_end)
        yield StreamBlock(
            volts=volts,
            codes=codes,
            gap_s=gap,
            t_mono=t_end,
            chunk_index=idx,
        )
        prev_end = t_end
        idx += 1
        if frames_left is not None:
            frames_left -= n
        if inter_block_pause_s > 0:
            time.sleep(inter_block_pause_s)


def acquire_continuous(
    dev: ADS1299,
    *,
    duration_s: float | None = None,
    total_frames: int | None = None,
    chunk_frames: int = DEFAULT_CHUNK_FRAMES,
    stop_event: threading.Event | None = None,
    vref: float = 4.5,
    gain: float = 24.0,
    inter_block_pause_s: float = 0.05,
) -> ContinuousResult:
    """Stitch segmented blocks into one continuous array + gap metadata."""
    chunks_v: list[np.ndarray] = []
    chunks_c: list[np.ndarray] = []
    gaps: list[float] = []
    sps = float(dev.sample_rate_sps())
    chunk = clamp_chunk_frames(chunk_frames)

    for block in iter_blocks(
        dev,
        chunk_frames=chunk,
        duration_s=duration_s,
        total_frames=total_frames,
        stop_event=stop_event,
        vref=vref,
        gain=gain,
        inter_block_pause_s=inter_block_pause_s,
    ):
        chunks_v.append(block.volts)
        chunks_c.append(block.codes)
        gaps.append(block.gap_s)

    if not chunks_v:
        return ContinuousResult(
            volts=np.zeros((0, data_mod.N_CH)),
            codes=np.zeros((0, data_mod.N_CH), dtype=np.int32),
            gaps_s=[],
            chunk_frames=chunk,
            sps=sps,
            n_blocks=0,
        )
    return ContinuousResult(
        volts=np.concatenate(chunks_v, axis=0),
        codes=np.concatenate(chunks_c, axis=0),
        gaps_s=gaps,
        chunk_frames=chunk,
        sps=sps,
        n_blocks=len(chunks_v),
    )
