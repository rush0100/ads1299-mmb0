from ads1299_mmb0.data import (
    BYTES_PER_FRAME,
    codes_to_volts,
    decode_spi_frames,
    decode_styx_i32_be,
    sign_extend_24,
)
from ads1299_mmb0.registers import chset


def test_sign_extend():
    assert sign_extend_24(0x000001) == 1
    assert sign_extend_24(0xFFFFFF) == -1
    assert sign_extend_24(0x800000) == -0x800000


def test_spi_frame():
    # status 0xC00000, ch1=+1, rest 0
    frame = bytes([0xC0, 0x00, 0x00, 0x00, 0x00, 0x01] + [0] * 21)
    status, ch = decode_spi_frames(frame)
    assert status[0] == 0xC00000
    assert ch[0, 0] == 1
    assert (ch[0, 1:] == 0).all()


def test_styx_i32_be_live_frame():
    # First frame from live N=64 capture (input-short).
    raw = bytes.fromhex(
        "ffc00000fffffc01fffffd1ffffffc63fffffddffffffccefffffce4fffffd06fffffbdc"
    )
    assert len(raw) == BYTES_PER_FRAME
    status, ch = decode_styx_i32_be(raw)
    assert status[0] == 0xC00000
    assert ch.shape == (1, 8)
    assert ch[0, 0] == -1023
    assert ch[0, 1] == -737


def test_chset():
    assert chset(gain=24, mux="short") == 0x61
    assert chset(gain=1, mux="normal") == 0x00


def test_volts_scale():
    import numpy as np

    v = codes_to_volts(np.array([[0, 1]]), vref=4.5, gain=24)
    assert v[0, 1] > 0
