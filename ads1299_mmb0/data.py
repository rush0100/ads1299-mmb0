"""Decode ADS1299 sample streams from /ads1299evm/data."""

from __future__ import annotations

import numpy as np

# Raw SPI frame on the wire (ADC): 24-bit status + 8 × 24-bit channels
SPI_FRAME = 27
N_CH = 8
# Live USBStyx `/data` packing (ads1299evm-pdk 0.0.27): each 24-bit field is
# stored as a big-endian int32 with the sample in the low 24 bits (top 8 = 0xFF
# padding observed). One EEG frame = status + 8 channels = 9 int32 = 36 bytes.
WORDS_PER_FRAME = N_CH + 1  # status + channels
BYTES_PER_FRAME = WORDS_PER_FRAME * 4  # 36


def sign_extend_24(raw: int) -> int:
    raw &= 0xFFFFFF
    if raw & 0x800000:
        raw -= 0x1000000
    return raw


def decode_spi_frames(buf: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Return (status[n], channels[n,8]) as int32 from packed 24-bit SPI frames."""
    n = len(buf) // SPI_FRAME
    buf = buf[: n * SPI_FRAME]
    status = np.empty(n, dtype=np.int32)
    ch = np.empty((n, N_CH), dtype=np.int32)
    for i in range(n):
        off = i * SPI_FRAME
        status[i] = (buf[off] << 16) | (buf[off + 1] << 8) | buf[off + 2]
        for c in range(N_CH):
            b = off + 3 + c * 3
            ch[i, c] = sign_extend_24((buf[b] << 16) | (buf[b + 1] << 8) | buf[b + 2])
    return status, ch


def decode_styx_i32_be(buf: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Decode live `/ads1299evm/data` payload (BE int32 × 9 per frame).

    Confirmed on FW 0.0.27: bytes ``ff c0 00 00`` → status ``0xC00000``;
    channel words hold a sign-extended 24-bit code in the low 24 bits.
    """
    n = len(buf) // BYTES_PER_FRAME
    buf = buf[: n * BYTES_PER_FRAME]
    if n == 0:
        return np.zeros(0, dtype=np.int32), np.zeros((0, N_CH), dtype=np.int32)
    words = np.frombuffer(buf, dtype=">u4").reshape(n, WORDS_PER_FRAME)
    status = (words[:, 0] & 0xFFFFFF).astype(np.int32)
    ch = np.empty((n, N_CH), dtype=np.int32)
    for c in range(N_CH):
        ch[:, c] = np.vectorize(sign_extend_24, otypes=[np.int32])(words[:, c + 1])
    return status, ch


def decode_i32_le(buf: bytes, n_channels: int = N_CH) -> np.ndarray:
    """Decode little-endian int32 samples (legacy guess).

    Prefer :func:`decode_styx_i32_be` for live MMB0 captures.
    """
    words = np.frombuffer(buf, dtype="<i4")
    stride = n_channels + 1
    if len(words) >= stride and len(words) % stride == 0:
        frames = words.reshape(-1, stride)
        return frames[:, 1:].copy()
    if len(words) % n_channels == 0:
        return words.reshape(-1, n_channels).copy()
    raise ValueError(
        f"buffer length {len(buf)} not aligned to {n_channels} or {stride} int32 words"
    )


def codes_to_volts(codes: np.ndarray, *, vref: float = 4.5, gain: float = 24.0) -> np.ndarray:
    """Input-referred volts for ADS1299 (full-scale ±Vref/gain, 24-bit)."""
    lsb = (2.0 * vref / gain) / (2**24)
    return codes.astype(np.float64) * lsb
