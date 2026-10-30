"""EVM register presets from SLAU443B workflows."""

from __future__ import annotations

from dataclasses import dataclass

from .registers import chset


@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    # styx name → value
    regs: dict[str, int]
    note: str = ""


def _all_ch(mux: str, gain: int = 24) -> dict[str, int]:
    return {f"ch{i}set": chset(gain=gain, mux=mux) for i in range(1, 9)}


# LOFF FLEAD_OFF[1:0]: 00=DC, 01=AC 7.8Hz, 10=AC 31.2Hz, 11=AC fDR/4 (ADS1299)
def _loff(flead: int, ilead: int = 0b00, comp_th: int = 0b000) -> int:
    return ((comp_th & 7) << 5) | ((ilead & 3) << 2) | (flead & 3)


PRESETS: dict[str, Preset] = {
    "input_short": Preset(
        name="Input short noise",
        description="All channels input-short, refbuf on, 250 SPS",
        regs={
            "config1": 0x96,  # DR=250, CLK_EN
            "config2": 0xC0,
            "config3": 0xE0,  # PD_REFBUF=1, BIASREF_INT, PD_BIAS
            "config4": 0x00,
            "loff": 0x00,
            **_all_ch("short", 24),
        },
        note="UG input-short noise test; jumpers factory default.",
    ),
    "internal_test": Preset(
        name="Internal test signal",
        description="INT_CAL square wave on all channels",
        regs={
            "config1": 0x96,
            "config2": 0xD0,  # INT_CAL on
            "config3": 0xE0,
            "config4": 0x00,
            **_all_ch("test", 24),
        },
        note="CONFIG2 INT_CAL; MUX=test. View on Scope/FFT.",
    ),
    "impedance_31hz": Preset(
        name="Impedance @ 31.2 Hz",
        description="AC lead-off excitation ~31.2 Hz",
        regs={
            "config1": 0x96,
            "config2": 0xC0,
            "config3": 0xE0,
            "config4": 0x00,  # PD_LOFF_COMP=0 → comparators enabled
            "loff": _loff(0b10),  # FLEAD=31.2 Hz
            "loffsensp": 0xFF,
            "loffsensn": 0xFF,
            **_all_ch("normal", 24),
        },
        note="Requires electrode/jumper setup (JP25/J6). Soft sets LOFF AC 31.2 Hz.",
    ),
    "impedance_fdr4": Preset(
        name="Impedance @ fDR/4",
        description="AC lead-off at fDR/4",
        regs={
            "config1": 0x96,  # 250 SPS → fDR/4 = 62.5 Hz
            "config2": 0xC0,
            "config3": 0xE0,
            "config4": 0x00,
            "loff": _loff(0b11),
            "loffsensp": 0xFF,
            "loffsensn": 0xFF,
            **_all_ch("normal", 24),
        },
        note="FLEAD_OFF=fDR/4. At 250 SPS → 62.5 Hz. Check jumpers per UG.",
    ),
    "cmrr_bias_meas": Preset(
        name="CMRR / BIAS_MEAS",
        description="Route BIASIN measurement path (mux=bias_meas)",
        regs={
            "config1": 0x96,
            "config2": 0xC0,
            "config3": 0xE0 | 0x10,  # BIAS_MEAS
            "config4": 0x00,
            **_all_ch("bias_meas", 24),
        },
        note="For CMRR: enter Input Amplitude in FFT panel after capture.",
    ),
}


# CONFIG bit field helpers -------------------------------------------------

def pack_config1(*, daisy: bool = False, clk_en: bool = True, dr: int = 0b110) -> int:
    # CONFIG1: bit7=1, DAISY, CLK_EN, bit4=1, bit3=0, DR[2:0]
    return (
        0x80
        | ((1 if daisy else 0) << 6)
        | ((1 if clk_en else 0) << 5)
        | 0x10
        | (dr & 7)
    )


def pack_config2(*, int_cal: bool = False, cal_amp: bool = False, cal_freq: int = 0) -> int:
    # bits 7:6 = 11
    return 0xC0 | ((1 if int_cal else 0) << 4) | ((1 if cal_amp else 0) << 2) | (cal_freq & 3)


def pack_config3(
    *,
    pd_refbuf: bool = True,
    bias_meas: bool = False,
    biasref_int: bool = True,
    pd_bias: bool = True,
) -> int:
    # bit6 and bit5 must be 1
    return (
        ((1 if pd_refbuf else 0) << 7)
        | 0x60
        | ((1 if bias_meas else 0) << 4)
        | ((1 if biasref_int else 0) << 3)
        | ((1 if pd_bias else 0) << 2)
    )


def pack_config4(*, pd_loff_comp: bool = False) -> int:
    return (1 if pd_loff_comp else 0) << 1


def pack_gpio(*, data: int = 0, control: int = 0) -> int:
    """GPIO[7:4]=data, GPIO[3:0]=control (1=output)."""
    return ((data & 0xF) << 4) | (control & 0xF)
