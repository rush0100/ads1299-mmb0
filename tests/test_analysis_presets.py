"""Unit tests for analysis + presets (SLAU443B parity helpers)."""

from __future__ import annotations

import numpy as np

from ads1299_mmb0.analysis import (
    channel_stats,
    cmrr_db,
    coherent_ideal_freq,
    fft_metrics,
    lead_off_bits,
    rfft_db,
)
from ads1299_mmb0.presets import (
    PRESETS,
    pack_config1,
    pack_config2,
    pack_config3,
    pack_config4,
    pack_gpio,
)


def test_channel_stats():
    v = np.array([[1.0, -1.0], [1.0, -1.0], [1.0, -1.0]])
    st = channel_stats(v)
    assert len(st) == 2
    assert abs(st[0].mean - 1.0) < 1e-9
    assert abs(st[1].rms - 1.0) < 1e-9
    assert abs(st[0].peak_peak) < 1e-9


def test_coherent_ideal_freq():
    # fs=250, N=1024, 1 cycle → 250/1024
    f = coherent_ideal_freq(250.0, 1024, n_cycles=1)
    assert abs(f - 250.0 / 1024) < 1e-12
    f3 = coherent_ideal_freq(250.0, 1024, n_cycles=2)  # bumped to odd 3
    assert abs(f3 - 250.0 * 3 / 1024) < 1e-12


def test_fft_metrics_sine():
    fs = 250.0
    n = 1024
    t = np.arange(n) / fs
    # coherent-ish tone
    f0 = coherent_ideal_freq(fs, n, 11)
    y = 0.5 * np.sin(2 * np.pi * f0 * t)
    m = fft_metrics(y, fs=fs, window="hann")
    assert m.snr_db > 40
    assert abs(m.fund_hz - f0) < fs / n * 2


def test_rfft_db_shape():
    y = np.random.randn(256)
    freqs, mag = rfft_db(y, fs=250.0, window="hamming")
    assert len(freqs) == len(mag) == 129


def test_cmrr_and_leadoff():
    assert cmrr_db(1.0, 0.001) == 60.0
    bits = lead_off_bits(0b0000_0101)
    assert bits[0] is True and bits[1] is False and bits[2] is True


def test_pack_config():
    assert pack_config1(daisy=False, clk_en=False, dr=0b110) == 0x96
    assert pack_config1(daisy=False, clk_en=True, dr=0b110) == 0xB6
    c2 = pack_config2(int_cal=True)
    assert c2 & 0x10
    c3 = pack_config3(pd_refbuf=True, biasref_int=True, pd_bias=True)
    assert c3 & 0x80 and c3 & 0x08
    assert pack_config4(pd_loff_comp=True) == 0x02
    assert pack_gpio(data=0b1010, control=0b0101) == 0xA5


def test_presets_have_required_keys():
    for key in ("input_short", "internal_test", "impedance_31hz", "impedance_fdr4"):
        p = PRESETS[key]
        assert "config1" in p.regs and "config3" in p.regs
        assert all(f"ch{i}set" in p.regs for i in range(1, 9))
