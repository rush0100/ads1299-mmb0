"""Unit tests for segmented continuous stream (no hardware required)."""

from __future__ import annotations

import os
import struct
import threading
import time

import numpy as np
import pytest

from ads1299_mmb0.data import BYTES_PER_FRAME, N_CH
from ads1299_mmb0.stream import (
    DEFAULT_CHUNK_FRAMES,
    MAX_FRAMES_THEORETICAL,
    SAFE_MAX_FRAMES,
    acquire_continuous,
    clamp_chunk_frames,
    iter_blocks,
)


def _fake_frame(status: int = 0xC00000, code: int = 100) -> bytes:
    words = [status & 0xFFFFFFFF] + [code & 0xFFFFFFFF] * N_CH
    return b"".join(struct.pack(">I", w & 0xFFFFFFFF) for w in words)


def _fake_block(n: int, code: int = 100) -> bytes:
    return b"".join(_fake_frame(code=code) for _ in range(n))


class FakeDev:
    def __init__(self, hang_after: int | None = None) -> None:
        self.calls: list[int] = []
        self.hang_after = hang_after
        self._n = 0

    def sample_rate_sps(self) -> float:
        return 250.0

    def acquire_raw(
        self,
        *,
        n_samples: int = 64,
        settle_s: float | None = None,
        timeout_s: float | None = None,
        ensure_defaults: bool = True,
        arm_data: bool = False,
    ) -> bytes:
        self.calls.append(n_samples)
        self._n += 1
        if self.hang_after is not None and self._n > self.hang_after:
            raise TimeoutError("simulated USB timeout")
        return _fake_block(n_samples, code=self._n)


def test_clamp_chunk_frames():
    assert clamp_chunk_frames(1) == 1
    assert clamp_chunk_frames(10_000) == SAFE_MAX_FRAMES
    assert clamp_chunk_frames(SAFE_MAX_FRAMES) <= MAX_FRAMES_THEORETICAL
    with pytest.raises(ValueError):
        clamp_chunk_frames(0)


def test_iter_blocks_total_frames():
    dev = FakeDev()
    blocks = list(
        iter_blocks(
            dev,
            chunk_frames=64,
            total_frames=150,
            inter_block_pause_s=0.0,
        )
    )
    assert len(blocks) == 3  # 64 + 64 + 22
    assert [b.volts.shape[0] for b in blocks] == [64, 64, 22]
    assert blocks[0].gap_s == 0.0
    assert blocks[1].gap_s >= 0.0
    assert blocks[2].chunk_index == 2
    assert sum(b.volts.shape[0] for b in blocks) == 150
    assert dev.calls == [64, 64, 22]


def test_acquire_continuous_stitches_and_gaps():
    dev = FakeDev()
    result = acquire_continuous(
        dev,
        total_frames=192,
        chunk_frames=64,
        inter_block_pause_s=0.01,
    )
    assert result.n_blocks == 3
    assert result.volts.shape == (192, 8)
    assert result.codes.shape == (192, 8)
    assert result.chunk_frames == 64
    assert result.sps == 250.0
    assert len(result.gaps_s) == 3
    assert result.gaps_s[0] == 0.0
    # later gaps include inter_block_pause + acquire wall time
    assert result.gaps_s[1] >= 0.01
    assert result.gaps_s[2] >= 0.01


def test_stop_event_halts_after_block():
    dev = FakeDev()
    stop = threading.Event()

    def killer():
        time.sleep(0.02)
        stop.set()

    threading.Thread(target=killer, daemon=True).start()
    blocks = list(
        iter_blocks(
            dev,
            chunk_frames=32,
            stop_event=stop,
            inter_block_pause_s=0.05,
        )
    )
    assert len(blocks) >= 1
    assert len(blocks) < 20


def test_default_chunk_under_buffer():
    assert DEFAULT_CHUNK_FRAMES * BYTES_PER_FRAME < 1_000_000
    assert DEFAULT_CHUNK_FRAMES <= SAFE_MAX_FRAMES


@pytest.mark.skipif(
    os.environ.get("ADS1299_E2E") != "1",
    reason="set ADS1299_E2E=1 with board attached",
)
def test_e2e_multi_block_continuous():
    from ads1299_mmb0.device import ADS1299

    with ADS1299.open(load_fw=True) as dev:
        dev.ensure_capture_defaults()
        result = acquire_continuous(
            dev,
            total_frames=192,
            chunk_frames=64,
            inter_block_pause_s=0.05,
        )
    assert result.n_blocks >= 2
    assert result.volts.shape[0] == 192
    assert result.volts.shape[1] == 8
    assert len(result.gaps_s) == result.n_blocks
    assert result.gaps_s[0] == 0.0
    assert any(g > 0 for g in result.gaps_s[1:])
