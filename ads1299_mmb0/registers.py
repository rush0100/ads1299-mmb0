"""ADS1299 register addresses and reset defaults (from EVM register map)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reg:
    addr: int
    name: str
    reset: int
    styx: str  # filename under /ads1299evm/conf/


REGS: tuple[Reg, ...] = (
    Reg(0x00, "ID", 0x00, "devid"),
    Reg(0x01, "CONFIG1", 0x96, "config1"),
    Reg(0x02, "CONFIG2", 0xC0, "config2"),
    Reg(0x03, "CONFIG3", 0x60, "config3"),
    Reg(0x04, "LOFF", 0x00, "loff"),
    Reg(0x05, "CH1SET", 0x60, "ch1set"),
    Reg(0x06, "CH2SET", 0x60, "ch2set"),
    Reg(0x07, "CH3SET", 0x60, "ch3set"),
    Reg(0x08, "CH4SET", 0x60, "ch4set"),
    Reg(0x09, "CH5SET", 0x60, "ch5set"),
    Reg(0x0A, "CH6SET", 0x60, "ch6set"),
    Reg(0x0B, "CH7SET", 0x60, "ch7set"),
    Reg(0x0C, "CH8SET", 0x60, "ch8set"),
    Reg(0x0D, "BIASSENSP", 0x00, "biassensp"),
    Reg(0x0E, "BIASSENSN", 0x00, "biassensn"),
    Reg(0x0F, "LOFF_SENSP", 0x00, "loffsensp"),
    Reg(0x10, "LOFF_SENSN", 0x00, "loffsensn"),
    Reg(0x11, "LOFF_FLIP", 0x00, "loffflip"),
    Reg(0x12, "LOFF_STATP", 0x00, "loffstatp"),
    Reg(0x13, "LOFF_STATN", 0x00, "loffstatn"),
    Reg(0x14, "GPIO", 0x00, "gpio"),
    Reg(0x15, "MISC1", 0x00, "misc1"),
    Reg(0x16, "MISC2", 0x00, "misc2"),
    Reg(0x17, "CONFIG4", 0x00, "config4"),
)

BY_NAME = {r.name.lower(): r for r in REGS}
BY_STYX = {r.styx.lower(): r for r in REGS}
BY_ADDR = {r.addr: r for r in REGS}

# Common mux / gain encodings (CHnSET)
MUX = {
    "normal": 0b000,
    "short": 0b001,
    "bias_meas": 0b010,
    "mvdd": 0b011,
    "temp": 0b100,
    "test": 0b101,
    "bias_drp": 0b110,
    "bias_drn": 0b111,
}

GAIN = {
    1: 0b000,
    2: 0b001,
    4: 0b010,
    6: 0b011,
    8: 0b100,
    12: 0b101,
    24: 0b110,
}


def chset(*, gain: int = 24, mux: str = "normal", pd: bool = False, srb2: bool = False) -> int:
    g = GAIN[gain]
    m = MUX[mux]
    return ((1 if pd else 0) << 7) | (g << 4) | ((1 if srb2 else 0) << 3) | m
