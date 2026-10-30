"""Command-line entry points."""

from __future__ import annotations

import argparse
import sys

from . import data as data_mod
from .device import ADS1299
from .firmware_loader import load_firmware, wait_for_styx
from .registers import chset
from .styx_client import StyxClient
from .styx_usb import StyxUSB
from .usb_ids import BOOT_PID, BOOT_VID, STYX_PID, STYX_VID


def load_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Load ADS1299EEG-FE firmware onto MMB0")
    p.add_argument(
        "-f",
        "--firmware",
        default=None,
        help="path to ads1299evm-pdk.bin (or set ADS1299_FIRMWARE; not shipped)",
    )
    p.add_argument(
        "--wait",
        action="store_true",
        help="wait until USBStyx appears after load",
    )
    args = p.parse_args(argv)

    if args.wait:
        wait_for_styx(args.firmware)
        print(f"USBStyx ready ({STYX_VID:#06x}:{STYX_PID:#06x})")
    else:
        load_firmware(args.firmware)
        print(
            f"Firmware written to bootloader ({BOOT_VID:#06x}:{BOOT_PID:#06x}). "
            f"Expect re-enumeration as {STYX_VID:#06x}:{STYX_PID:#06x}."
        )
    return 0


def shell_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tiny Styx shell for ADS1299EEG-FE")
    p.add_argument("--no-load", action="store_true", help="do not auto-load firmware")
    p.add_argument(
        "-f",
        "--firmware",
        default=None,
        help="path to ads1299evm-pdk.bin (or set ADS1299_FIRMWARE; not shipped)",
    )
    args = p.parse_args(argv)

    if not args.no_load:
        wait_for_styx(args.firmware)

    with StyxUSB() as usb, StyxClient(usb) as client:
        print("Connected. Commands: ls PATH | cat PATH | echo TEXT > PATH | q")
        while True:
            try:
                line = input("styx> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line in {"q", "quit", "exit"}:
                break
            if line.startswith("cat "):
                path = line[4:].strip()
                try:
                    print(client.read_text(path))
                except Exception as e:
                    print("error:", e)
            elif line.startswith("echo ") and ">" in line:
                left, path = line.split(">", 1)
                text = left[5:].strip().strip('"')
                path = path.strip()
                try:
                    client.write_text(path, text)
                except Exception as e:
                    print("error:", e)
            elif line.startswith("ls"):
                path = line[2:].strip() or "/"
                try:
                    # Directory listing via reading path if firmware exposes it;
                    # otherwise cat known index files.
                    print(client.read_text(path))
                except Exception as e:
                    print("error:", e, "(try: cat /version)")
            else:
                print("unknown command")
    return 0


def gui_main(argv: list[str] | None = None) -> int:
    """Launch the evaluation GUI (tkinter + matplotlib)."""
    from ads1299_mmb0.gui.app import main as _gui

    _gui()
    return 0


def capture_main(argv: list[str] | None = None) -> int:
    """Block or segmented-continuous capture → stdout (+ optional files)."""
    import json
    from pathlib import Path

    import numpy as np

    from .stream import DEFAULT_CHUNK_FRAMES, acquire_continuous

    p = argparse.ArgumentParser(
        description="Capture ADS1299EEG-FE via USBStyx (block or segmented continuous)"
    )
    p.add_argument("-n", "--frames", type=int, default=64, help="EEG frames for one-shot block")
    p.add_argument(
        "--duration",
        type=float,
        default=None,
        help="segmented continuous: run for SEC (stitches blocks ≤ MMB0 buffer)",
    )
    p.add_argument(
        "--total-frames",
        type=int,
        default=None,
        help="segmented continuous: stop after this many EEG frames",
    )
    p.add_argument(
        "--chunk",
        type=int,
        default=DEFAULT_CHUNK_FRAMES,
        help=f"frames per MMB0 block for continuous (default {DEFAULT_CHUNK_FRAMES})",
    )
    p.add_argument("--no-load", action="store_true")
    p.add_argument(
        "-f",
        "--firmware",
        default=None,
        help="path to ads1299evm-pdk.bin (or set ADS1299_FIRMWARE; not shipped)",
    )
    p.add_argument("-o", "--out", help="write raw bytes to path (one-shot only)")
    p.add_argument("--npy", help="write float64 volts Nx8 to .npy")
    p.add_argument("--meta", help="write continuous metadata JSON (gaps, chunk, sps)")
    p.add_argument("--mux", default="short", choices=["short", "normal", "test", "temp"])
    p.add_argument("--gain", type=int, default=24)
    args = p.parse_args(argv)

    continuous = args.duration is not None or args.total_frames is not None

    with ADS1299.open(load_fw=not args.no_load, firmware=args.firmware) as dev:
        print("version", dev.read_path("/version"), "devid", hex(dev.read_register("devid")))
        dev.ensure_capture_defaults()
        for ch in range(1, 9):
            dev.write_register(f"ch{ch}set", chset(gain=args.gain, mux=args.mux))

        if continuous:
            print(
                f"segmented continuous duration={args.duration} "
                f"total_frames={args.total_frames} chunk={args.chunk}"
            )
            result = acquire_continuous(
                dev,
                duration_s=args.duration,
                total_frames=args.total_frames,
                chunk_frames=args.chunk,
                gain=float(args.gain),
            )
            volts, codes = result.volts, result.codes
            print(
                f"frames {codes.shape} blocks={result.n_blocks} "
                f"chunk={result.chunk_frames} sps={result.sps:.1f}"
            )
            if result.gaps_s:
                gaps_ms = [g * 1000 for g in result.gaps_s[1:]]  # skip first 0
                if gaps_ms:
                    print(
                        f"inter-block gaps ms: "
                        f"mean={sum(gaps_ms)/len(gaps_ms):.1f} "
                        f"max={max(gaps_ms):.1f} n={len(gaps_ms)}"
                    )
            if not codes.size:
                print("FAIL no continuous data")
                return 1
            if args.npy:
                np.save(args.npy, volts)
                print("wrote", args.npy)
            meta_path = args.meta
            if meta_path is None and args.npy:
                meta_path = str(Path(args.npy).with_suffix("")) + "_meta.json"
            if meta_path:
                Path(meta_path).write_text(
                    json.dumps(
                        {
                            "mode": "segmented_continuous",
                            "frames": int(codes.shape[0]),
                            "n_blocks": result.n_blocks,
                            "chunk_frames": result.chunk_frames,
                            "sps": result.sps,
                            "gaps_s": result.gaps_s,
                            "note": "Not zero-gap USB stream; stock MMB0 buffer-then-USB.",
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                print("wrote", meta_path)
            return 0

        raw = dev.acquire_raw(n_samples=args.frames, ensure_defaults=False, arm_data=False)
        print(f"raw {len(raw)} B (expect {data_mod.BYTES_PER_FRAME * args.frames})")
        if not raw:
            print("FAIL empty /data — power-cycle wall wart if USB previously wedged")
            return 1
        if args.out:
            open(args.out, "wb").write(raw)
            print("wrote", args.out)
        st, codes = data_mod.decode_styx_i32_be(raw)
        volts = data_mod.codes_to_volts(codes, gain=float(args.gain))
        print(f"frames {codes.shape} status0={hex(int(st[0]))}")
        print("codes mean", codes.mean(0).astype(int))
        print("uV rms", [round(float(x), 2) for x in (volts.std(0) * 1e6)])
        if args.npy:
            np.save(args.npy, volts)
            print("wrote", args.npy)
    return 0


if __name__ == "__main__":
    sys.exit(shell_main())
