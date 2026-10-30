"""Time/frequency analysis helpers (SLAU443B Analysis tab parity)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

WINDOWS = {
    "none": lambda n: np.ones(n),
    "hann": np.hanning,
    "hamming": np.hamming,
    "blackman": np.blackman,
    "flattop": lambda n: np.kaiser(n, 8.6),  # approx flat-top for eval
}


@dataclass(frozen=True)
class ChannelStats:
    mean: float
    rms: float
    peak_peak: float


@dataclass(frozen=True)
class AcParams:
    n_harmonics: int = 5
    dc_leak_bins: int = 1
    fund_leak_bins: int = 1
    harm_leak_bins: int = 1


@dataclass(frozen=True)
class FftMetrics:
    snr_db: float
    thd_db: float
    enob: float
    fund_hz: float
    fund_db: float


def channel_stats(volts: np.ndarray) -> list[ChannelStats]:
    """Per-channel mean / RMS / peak-peak for shape (N, C)."""
    out: list[ChannelStats] = []
    if volts.ndim != 2 or volts.shape[0] == 0:
        return out
    for c in range(volts.shape[1]):
        y = volts[:, c].astype(np.float64)
        out.append(
            ChannelStats(
                mean=float(y.mean()),
                rms=float(np.sqrt(np.mean(y * y))),
                peak_peak=float(y.max() - y.min()),
            )
        )
    return out


def coherent_ideal_freq(fs: float, n_total: int, n_cycles: int = 1) -> float:
    """Ideal AIN frequency for coherent sampling: FAIN = fs * NWINDOW / NTOTAL."""
    n_total = max(int(n_total), 1)
    # Prefer odd integer cycles near n_cycles
    cycles = max(int(n_cycles), 1)
    if cycles % 2 == 0:
        cycles += 1
    return float(fs) * cycles / n_total


def apply_window(y: np.ndarray, name: str) -> np.ndarray:
    key = (name or "hann").lower()
    fn = WINDOWS.get(key, np.hanning)
    w = fn(len(y))
    return y.astype(np.float64) * w


def rfft_db(
    y: np.ndarray,
    *,
    fs: float,
    window: str = "hann",
    dbfs: bool = True,
    full_scale: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (freq_hz, magnitude_db) for a 1-D real signal."""
    yw = apply_window(y, window)
    spec = np.fft.rfft(yw)
    mag = np.abs(spec)
    # Normalize by N/2 for single-sided amplitude estimate
    n = max(len(yw), 1)
    mag = mag * (2.0 / n)
    mag[0] *= 0.5
    if dbfs:
        ref = max(float(full_scale), 1e-30)
        db = 20.0 * np.log10(np.maximum(mag / ref, 1e-30))
    else:
        # dBc later relative to fund — return amplitude dB re 1.0 V
        db = 20.0 * np.log10(np.maximum(mag, 1e-30))
    freqs = np.fft.rfftfreq(n, d=1.0 / max(fs, 1e-12))
    return freqs, db


def _bin_mask(n_bins: int, center: int, half_width: int) -> np.ndarray:
    m = np.zeros(n_bins, dtype=bool)
    lo = max(0, center - half_width)
    hi = min(n_bins, center + half_width + 1)
    m[lo:hi] = True
    return m


def fft_metrics(
    y: np.ndarray,
    *,
    fs: float,
    window: str = "hann",
    params: AcParams | None = None,
    band: tuple[float, float] | None = None,
) -> FftMetrics:
    """SNR / THD / ENOB from a single-channel voltage series."""
    params = params or AcParams()
    yw = apply_window(y, window)
    n = len(yw)
    spec = np.fft.rfft(yw)
    power = (np.abs(spec) ** 2).astype(np.float64)
    freqs = np.fft.rfftfreq(n, d=1.0 / max(fs, 1e-12))
    nb = len(power)

    # Exclude DC leakage
    usable = np.ones(nb, dtype=bool)
    usable[: max(1, params.dc_leak_bins + 1)] = False

    if band is not None:
        lo, hi = band
        usable &= (freqs >= lo) & (freqs <= hi)

    search = power.copy()
    search[~usable] = 0.0
    fund_bin = int(np.argmax(search)) if search.max() > 0 else 1
    fund_hz = float(freqs[fund_bin])
    fund_p = float(power[fund_bin])

    fund_mask = _bin_mask(nb, fund_bin, params.fund_leak_bins)
    harm_mask = np.zeros(nb, dtype=bool)
    for h in range(2, params.n_harmonics + 2):
        b = int(round(fund_bin * h))
        if 0 < b < nb:
            harm_mask |= _bin_mask(nb, b, params.harm_leak_bins)

    noise_mask = usable & ~fund_mask & ~harm_mask
    noise_p = float(power[noise_mask].sum()) if noise_mask.any() else 1e-30
    harm_p = float(power[harm_mask & usable].sum()) if (harm_mask & usable).any() else 0.0

    snr = 10.0 * np.log10(max(fund_p, 1e-30) / max(noise_p, 1e-30))
    thd = 10.0 * np.log10(max(harm_p, 1e-30) / max(fund_p, 1e-30))
    # ENOB from SNR (ideal sine): SNR ≈ 6.02·ENOB + 1.76
    enob = (snr - 1.76) / 6.02
    fund_db = 10.0 * np.log10(max(fund_p, 1e-30))
    return FftMetrics(
        snr_db=float(snr),
        thd_db=float(thd),
        enob=float(enob),
        fund_hz=fund_hz,
        fund_db=float(fund_db),
    )


def cmrr_db(signal_amp_v: float, common_amp_v: float) -> float:
    """CMRR = 20·log10(Vdiff_gain / Vcm_gain) with user input amplitude as reference."""
    sig = max(abs(float(signal_amp_v)), 1e-30)
    cm = max(abs(float(common_amp_v)), 1e-30)
    return float(20.0 * np.log10(sig / cm))


def lead_off_bits(stat_byte: int) -> list[bool]:
    """Return 8 channel flags; True = connected (UG: disconnected bit goes low)."""
    # Active-low disconnect: bit==0 → disconnected → connected=False when bit clear? 
    # UG: "When a lead is disconnected, the corresponding register bit activates low."
    # GUI green=connected when bit high after invert of "disconnect".
    # connected when bit is 1 (not activated low)
    return [bool((stat_byte >> i) & 1) for i in range(8)]
