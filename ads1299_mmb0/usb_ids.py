"""USB identifiers used by MMB0 + ADS1299EEG-FE firmware."""

# TMS320VC5509A USB bootloader (before DSP image is loaded)
BOOT_VID = 0x0451
BOOT_PID = 0x9001

# USBStyx device after ads1299evm-pdk.bin is running
STYX_VID = 0x0451
STYX_PID = 0x5718

BOOT_OUT_EP = 0x06  # bulk OUT used by TI dsploader
STYX_OUT_EP = 0x01
STYX_IN_EP = 0x81
