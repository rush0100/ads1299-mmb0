"""ADS1299EEG-FE evaluation GUI — SLAU443B LabVIEW functional parity."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from ads1299_mmb0.analysis import (
    WINDOWS,
    AcParams,
    channel_stats,
    cmrr_db,
    coherent_ideal_freq,
    fft_metrics,
    lead_off_bits,
    rfft_db,
)
from ads1299_mmb0.gui.worker import DeviceSession
from ads1299_mmb0.presets import (
    PRESETS,
    pack_config1,
    pack_config2,
    pack_config3,
    pack_config4,
    pack_gpio,
)
from ads1299_mmb0.registers import GAIN, MUX, REGS, chset
from ads1299_mmb0.stream import DEFAULT_CHUNK_FRAMES
from ads1299_mmb0.usb_ids import BOOT_PID, BOOT_VID, STYX_PID, STYX_VID

DR_LABELS = {
    0b000: "16 kSPS",
    0b001: "8 kSPS",
    0b010: "4 kSPS",
    0b011: "2 kSPS",
    0b100: "1 kSPS",
    0b101: "500 SPS",
    0b110: "250 SPS",
}
MUX_LABELS = list(MUX.keys())
GAIN_LABELS = list(GAIN.keys())
CH_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
]


class HexSpin(ttk.Frame):
    def __init__(self, master, label: str, on_apply: Callable[[int], None], width: int = 12):
        super().__init__(master)
        ttk.Label(self, text=label, width=width).pack(side=tk.LEFT)
        self.var = tk.StringVar(value="0x00")
        ttk.Entry(self, textvariable=self.var, width=8).pack(side=tk.LEFT, padx=4)
        ttk.Button(self, text="Set", width=4, command=self._apply).pack(side=tk.LEFT)
        self._on_apply = on_apply

    def _apply(self) -> None:
        text = self.var.get().strip().lower().replace("0x", "")
        self._on_apply(int(text, 16) & 0xFF)

    def set_value(self, value: int) -> None:
        self.var.set(f"0x{value & 0xFF:02X}")

    def get_value(self) -> int:
        return int(self.var.get().strip().lower().replace("0x", ""), 16) & 0xFF


class MainApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ADS1299EEG-FE — Python EVM (SLAU443B parity)")
        self.geometry("1280x820")
        self.minsize(1024, 700)
        self.session = DeviceSession()
        self._busy = False
        self._streaming = False
        self._ch_enabled = [tk.BooleanVar(value=True) for _ in range(8)]
        self._scope_zoom_ch = tk.StringVar(value="all")
        self._hist_bins = tk.IntVar(value=64)
        self._fft_window = tk.StringVar(value="hann")
        self._fft_dbfs = tk.BooleanVar(value=True)
        self._n_harm = tk.IntVar(value=5)
        self._dc_leak = tk.IntVar(value=1)
        self._fund_leak = tk.IntVar(value=1)
        self._harm_leak = tk.IntVar(value=1)
        self._cmrr_amp = tk.DoubleVar(value=1.0)
        self._band_lo = tk.DoubleVar(value=0.0)
        self._band_hi = tk.DoubleVar(value=125.0)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(400, self._poll_usb)

    def _build(self) -> None:
        style = ttk.Style(self)
        if "aqua" not in style.theme_names():
            style.theme_use("clam")

        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text="ADS1299EEG-FE", font=("Helvetica", 16, "bold")).pack(side=tk.LEFT)
        ttk.Label(top, text="  MMB0 / USBStyx", foreground="#555").pack(side=tk.LEFT)
        self.conn_btn = ttk.Button(top, text="Connect", command=self._connect)
        self.conn_btn.pack(side=tk.RIGHT, padx=4)
        self.disc_btn = ttk.Button(top, text="Disconnect", command=self._disconnect, state=tk.DISABLED)
        self.disc_btn.pack(side=tk.RIGHT, padx=4)
        self.refresh_btn = ttk.Button(top, text="Read Registers", command=self._read_regs, state=tk.DISABLED)
        self.refresh_btn.pack(side=tk.RIGHT, padx=4)
        self.loff_btn = ttk.Button(
            top, text="Show/Poll Lead-Off", command=self._open_loff_dialog, state=tk.DISABLED
        )
        self.loff_btn.pack(side=tk.RIGHT, padx=4)

        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress.pack(fill=tk.X, padx=8)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.tab_about = ttk.Frame(self.notebook, padding=12)
        self.tab_regs = ttk.Frame(self.notebook, padding=8)
        self.tab_analysis = ttk.Frame(self.notebook, padding=8)
        self.tab_save = ttk.Frame(self.notebook, padding=12)
        self.tab_mmb0 = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.tab_about, text="About")
        self.notebook.add(self.tab_regs, text="ADC Registers")
        self.notebook.add(self.tab_analysis, text="Analysis")
        self.notebook.add(self.tab_save, text="Save")
        self.notebook.add(self.tab_mmb0, text="MMB0")

        self._hex: dict[str, HexSpin] = {}
        self._build_about()
        self._build_registers()
        self._build_analysis()
        self._build_save()
        self._build_mmb0()

        self.status = tk.StringVar(value="Disconnected")
        ttk.Label(self, textvariable=self.status, anchor=tk.W, padding=6).pack(fill=tk.X, side=tk.BOTTOM)

    # --- About ------------------------------------------------------------------
    def _build_about(self) -> None:
        f = self.tab_about
        ttk.Label(f, text="EEG Front-End Performance Demonstration Kit", font=("Helvetica", 14, "bold")).pack(
            anchor=tk.W
        )
        ttk.Label(
            f,
            text=(
                "Python EVM client — functional parity with SLAU443B LabVIEW software\n"
                "(registers, lead-off poll, scope/FFT/histogram/analysis, impedance presets, save).\n"
                "Block capture only (MMB0 buffer-then-USB). Eval/lab use — not for diagnosis.\n\n"
                "Impedance presets need matching jumpers (JP25/J6) per User Guide."
            ),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=8)
        self.about_info = tk.StringVar(value="Device: (not connected)")
        ttk.Label(f, textvariable=self.about_info, wraplength=900).pack(anchor=tk.W, pady=4)
        ttk.Label(
            f,
            text=f"USB IDs: boot {BOOT_VID:#06x}:{BOOT_PID:#06x} → styx {STYX_VID:#06x}:{STYX_PID:#06x}",
            foreground="#444",
        ).pack(anchor=tk.W)

    # --- Registers --------------------------------------------------------------
    def _build_registers(self) -> None:
        nb = ttk.Notebook(self.tab_regs)
        nb.pack(fill=tk.BOTH, expand=True)
        self.reg_global = ttk.Frame(nb, padding=8)
        self.reg_ch = ttk.Frame(nb, padding=8)
        self.reg_loff = ttk.Frame(nb, padding=8)
        self.reg_gpio = ttk.Frame(nb, padding=8)
        self.reg_map = ttk.Frame(nb, padding=8)
        nb.add(self.reg_global, text="Global")
        nb.add(self.reg_ch, text="Channels")
        nb.add(self.reg_loff, text="LOFF & BIAS")
        nb.add(self.reg_gpio, text="GPIO / Other")
        nb.add(self.reg_map, text="Register Map")

        g = self.reg_global
        ttk.Label(g, text="CONFIG bit fields", font=("Helvetica", 11, "bold")).pack(anchor=tk.W)
        # CONFIG1
        r1 = ttk.LabelFrame(g, text="CONFIG1", padding=6)
        r1.pack(fill=tk.X, pady=4)
        self.cfg1_daisy = tk.BooleanVar()
        self.cfg1_clken = tk.BooleanVar(value=True)
        self.dr_var = tk.StringVar(value="250 SPS")
        ttk.Checkbutton(r1, text="DAISY_EN", variable=self.cfg1_daisy).pack(side=tk.LEFT)
        ttk.Checkbutton(r1, text="CLK_EN", variable=self.cfg1_clken).pack(side=tk.LEFT, padx=8)
        ttk.Label(r1, text="DR").pack(side=tk.LEFT)
        ttk.Combobox(
            r1, textvariable=self.dr_var, values=list(DR_LABELS.values()), width=12, state="readonly"
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(r1, text="Apply CONFIG1", command=self._apply_config1).pack(side=tk.LEFT, padx=8)

        r2 = ttk.LabelFrame(g, text="CONFIG2", padding=6)
        r2.pack(fill=tk.X, pady=4)
        self.cfg2_intcal = tk.BooleanVar()
        self.cfg2_calamp = tk.BooleanVar()
        self.cfg2_calfreq = tk.IntVar(value=0)
        ttk.Checkbutton(r2, text="INT_CAL", variable=self.cfg2_intcal).pack(side=tk.LEFT)
        ttk.Checkbutton(r2, text="CAL_AMP", variable=self.cfg2_calamp).pack(side=tk.LEFT, padx=8)
        ttk.Label(r2, text="CAL_FREQ").pack(side=tk.LEFT)
        ttk.Combobox(r2, textvariable=self.cfg2_calfreq, values=[0, 1, 2, 3], width=4, state="readonly").pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(r2, text="Apply CONFIG2", command=self._apply_config2).pack(side=tk.LEFT, padx=8)

        r3 = ttk.LabelFrame(g, text="CONFIG3", padding=6)
        r3.pack(fill=tk.X, pady=4)
        self.cfg3_refbuf = tk.BooleanVar(value=True)
        self.cfg3_biasmeas = tk.BooleanVar()
        self.cfg3_biasref = tk.BooleanVar(value=True)
        self.cfg3_pdbias = tk.BooleanVar(value=True)
        for t, v in (
            ("PD_REFBUF on", self.cfg3_refbuf),
            ("BIAS_MEAS", self.cfg3_biasmeas),
            ("BIASREF_INT", self.cfg3_biasref),
            ("PD_BIAS on", self.cfg3_pdbias),
        ):
            ttk.Checkbutton(r3, text=t, variable=v).pack(side=tk.LEFT, padx=4)
        ttk.Button(r3, text="Apply CONFIG3", command=self._apply_config3).pack(side=tk.LEFT, padx=8)

        r4 = ttk.LabelFrame(g, text="CONFIG4 / LOFF hex", padding=6)
        r4.pack(fill=tk.X, pady=4)
        self.cfg4_pdloff = tk.BooleanVar()
        ttk.Checkbutton(r4, text="PD_LOFF_COMP", variable=self.cfg4_pdloff).pack(side=tk.LEFT)
        ttk.Button(r4, text="Apply CONFIG4", command=self._apply_config4).pack(side=tk.LEFT, padx=8)

        ttk.Label(g, text="Advanced hex", font=("Helvetica", 10, "bold")).pack(anchor=tk.W, pady=(8, 0))
        for key in ("config1", "config2", "config3", "config4", "loff"):
            w = HexSpin(g, key.upper(), lambda v, k=key: self._write_reg(k, v))
            w.pack(anchor=tk.W, pady=1)
            self._hex[key] = w

        btns = ttk.Frame(g)
        btns.pack(anchor=tk.W, pady=8)
        ttk.Button(btns, text="Software Reset", command=lambda: self._write_reg("reset", 1)).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Sleep", command=lambda: self._write_reg("sleep", 1)).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Wake", command=lambda: self._write_reg("sleep", 0)).pack(side=tk.LEFT, padx=4)

        # Channels (unchanged structure)
        chf = self.reg_ch
        head = ttk.Frame(chf)
        head.pack(fill=tk.X, pady=4)
        ttk.Label(head, text="Apply all →").pack(side=tk.LEFT)
        self.all_gain = tk.IntVar(value=24)
        self.all_mux = tk.StringVar(value="normal")
        ttk.Combobox(head, textvariable=self.all_gain, values=GAIN_LABELS, width=5, state="readonly").pack(
            side=tk.LEFT, padx=4
        )
        ttk.Combobox(head, textvariable=self.all_mux, values=MUX_LABELS, width=10, state="readonly").pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(head, text="Set all channels", command=self._apply_all_ch).pack(side=tk.LEFT, padx=4)

        self._ch_gain, self._ch_mux, self._ch_pd, self._ch_srb2 = [], [], [], []
        grid = ttk.Frame(chf)
        grid.pack(fill=tk.X, pady=6)
        for col, t in enumerate(("CH", "Gain", "MUX", "PD", "SRB2", "Hex")):
            ttk.Label(grid, text=t).grid(row=0, column=col)
        for i in range(8):
            ttk.Label(grid, text=f"{i+1}").grid(row=i + 1, column=0, padx=4)
            gv, mv = tk.IntVar(value=24), tk.StringVar(value="normal")
            pd, srb = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
            self._ch_gain.append(gv)
            self._ch_mux.append(mv)
            self._ch_pd.append(pd)
            self._ch_srb2.append(srb)
            ttk.Combobox(grid, textvariable=gv, values=GAIN_LABELS, width=5, state="readonly").grid(
                row=i + 1, column=1
            )
            ttk.Combobox(grid, textvariable=mv, values=MUX_LABELS, width=10, state="readonly").grid(
                row=i + 1, column=2
            )
            ttk.Checkbutton(grid, variable=pd).grid(row=i + 1, column=3)
            ttk.Checkbutton(grid, variable=srb).grid(row=i + 1, column=4)
            hx = HexSpin(grid, f"ch{i+1}set", lambda v, n=i: self._write_reg(f"ch{n+1}set", v), width=8)
            hx.grid(row=i + 1, column=5, sticky=tk.W)
            self._hex[f"ch{i+1}set"] = hx
            ttk.Button(grid, text="Apply", width=6, command=lambda n=i: self._apply_one_ch(n)).grid(
                row=i + 1, column=6, padx=4
            )

        lf = self.reg_loff
        for key in (
            "loff",
            "loffsensp",
            "loffsensn",
            "loffflip",
            "loffstatp",
            "loffstatn",
            "biassensp",
            "biassensn",
        ):
            if key == "loff" and key in self._hex:
                continue
            w = HexSpin(lf, key.upper(), lambda v, k=key: self._write_reg(k, v))
            w.pack(anchor=tk.W, pady=2)
            self._hex[key] = w
        ttk.Button(lf, text="Show/Poll Lead-Off Status…", command=self._open_loff_dialog).pack(
            anchor=tk.W, pady=8
        )

        go = self.reg_gpio
        gf = ttk.LabelFrame(go, text="GPIO (data[7:4] / ctrl[3:0]=1 output)", padding=6)
        gf.pack(fill=tk.X, pady=4)
        self.gpio_data = [tk.BooleanVar() for _ in range(4)]
        self.gpio_ctrl = [tk.BooleanVar() for _ in range(4)]
        rowd = ttk.Frame(gf)
        rowd.pack(anchor=tk.W)
        ttk.Label(rowd, text="DATA").pack(side=tk.LEFT)
        for i, v in enumerate(self.gpio_data):
            ttk.Checkbutton(rowd, text=f"D{i+1}", variable=v).pack(side=tk.LEFT)
        rowc = ttk.Frame(gf)
        rowc.pack(anchor=tk.W)
        ttk.Label(rowc, text="CTRL").pack(side=tk.LEFT)
        for i, v in enumerate(self.gpio_ctrl):
            ttk.Checkbutton(rowc, text=f"C{i+1}", variable=v).pack(side=tk.LEFT)
        ttk.Button(gf, text="Apply GPIO", command=self._apply_gpio).pack(anchor=tk.W, pady=4)

        for key in ("gpio", "misc1", "misc2", "devid"):
            w = HexSpin(go, key.upper(), lambda v, k=key: self._write_reg(k, v))
            w.pack(anchor=tk.W, pady=2)
            self._hex[key] = w
        self.srb1 = tk.BooleanVar(value=False)
        ttk.Checkbutton(go, text="SRB1 enable (MISC1 bit5)", variable=self.srb1, command=self._apply_srb1).pack(
            anchor=tk.W, pady=6
        )

        cols = ("addr", "name", "styx", "value")
        tree = ttk.Treeview(self.reg_map, columns=cols, show="headings", height=20)
        for c, w in zip(cols, (70, 120, 120, 80)):
            tree.heading(c, text=c.upper())
            tree.column(c, width=w, anchor=tk.CENTER)
        tree.pack(fill=tk.BOTH, expand=True)
        self.reg_tree = tree
        for reg in REGS:
            tree.insert("", tk.END, iid=reg.styx, values=(f"0x{reg.addr:02X}", reg.name, reg.styx, "—"))

    # --- Analysis ---------------------------------------------------------------
    def _build_analysis(self) -> None:
        left = ttk.Frame(self.tab_analysis)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        right = ttk.Frame(self.tab_analysis)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(left, text="Capture", font=("Helvetica", 11, "bold")).pack(anchor=tk.W)
        self.n_samples = tk.IntVar(value=1024)
        ttk.Label(left, text="Frames (prefer 2^n for FFT)").pack(anchor=tk.W)
        ttk.Entry(left, textvariable=self.n_samples, width=10).pack(anchor=tk.W)
        self.vref_var = tk.DoubleVar(value=4.5)
        self.gain_var = tk.DoubleVar(value=24.0)
        ttk.Label(left, text="Vref (single source)").pack(anchor=tk.W, pady=(8, 0))
        ttk.Entry(left, textvariable=self.vref_var, width=10).pack(anchor=tk.W)
        ttk.Label(left, text="Gain").pack(anchor=tk.W)
        ttk.Entry(left, textvariable=self.gain_var, width=10).pack(anchor=tk.W)
        self.acq_btn = ttk.Button(left, text="Acquire", command=self._acquire, state=tk.DISABLED)
        self.acq_btn.pack(anchor=tk.W, pady=8)

        cont = ttk.LabelFrame(left, text="Continuous (segmented)", padding=4)
        cont.pack(fill=tk.X, pady=6)
        ttk.Label(cont, text="Chunk frames").pack(anchor=tk.W)
        self.chunk_frames = tk.IntVar(value=min(DEFAULT_CHUNK_FRAMES, 256))
        ttk.Entry(cont, textvariable=self.chunk_frames, width=10).pack(anchor=tk.W)
        ttk.Label(cont, text="Duration s (0=until Stop)").pack(anchor=tk.W)
        self.stream_duration = tk.DoubleVar(value=0.0)
        ttk.Entry(cont, textvariable=self.stream_duration, width=10).pack(anchor=tk.W)
        rowc = ttk.Frame(cont)
        rowc.pack(fill=tk.X, pady=4)
        self.stream_btn = ttk.Button(
            rowc, text="Start", command=self._stream_start, state=tk.DISABLED, width=8
        )
        self.stream_btn.pack(side=tk.LEFT, padx=2)
        self.stream_stop_btn = ttk.Button(
            rowc, text="Stop", command=self._stream_stop, state=tk.DISABLED, width=8
        )
        self.stream_stop_btn.pack(side=tk.LEFT, padx=2)
        self.stream_status = tk.StringVar(value="Idle (not zero-gap USB)")
        ttk.Label(cont, textvariable=self.stream_status, wraplength=180).pack(anchor=tk.W)

        ttk.Label(left, text="Presets", font=("Helvetica", 11, "bold")).pack(anchor=tk.W, pady=(8, 0))
        for key, preset in PRESETS.items():
            ttk.Button(
                left, text=preset.name, command=lambda k=key: self._run_preset(k), width=22
            ).pack(anchor=tk.W, pady=1)

        ttk.Label(left, text="Channels").pack(anchor=tk.W, pady=(8, 0))
        for i in range(8):
            ttk.Checkbutton(
                left, text=f"CH{i+1}", variable=self._ch_enabled[i], command=self._redraw_plots
            ).pack(anchor=tk.W)

        ttk.Label(left, text="Scope zoom").pack(anchor=tk.W, pady=(8, 0))
        ttk.Combobox(
            left,
            textvariable=self._scope_zoom_ch,
            values=["all"] + [f"CH{i+1}" for i in range(8)],
            width=8,
            state="readonly",
        ).pack(anchor=tk.W)
        ttk.Button(left, text="Redraw", command=self._redraw_plots).pack(anchor=tk.W, pady=4)

        anb = ttk.Notebook(right)
        anb.pack(fill=tk.BOTH, expand=True)
        self.scope_frame = ttk.Frame(anb)
        self.fft_frame = ttk.Frame(anb)
        self.hist_frame = ttk.Frame(anb)
        self.stats_frame = ttk.Frame(anb)
        anb.add(self.scope_frame, text="Scope")
        anb.add(self.fft_frame, text="FFT")
        anb.add(self.hist_frame, text="Histogram")
        anb.add(self.stats_frame, text="Analysis")

        self.fig_scope = Figure(figsize=(7, 3.6), dpi=100)
        self.ax_scope = self.fig_scope.add_subplot(111)
        self.canvas_scope = FigureCanvasTkAgg(self.fig_scope, master=self.scope_frame)
        self.canvas_scope.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(self.canvas_scope, self.scope_frame)

        fft_ctrl = ttk.Frame(self.fft_frame)
        fft_ctrl.pack(fill=tk.X)
        ttk.Label(fft_ctrl, text="Window").pack(side=tk.LEFT)
        ttk.Combobox(
            fft_ctrl,
            textvariable=self._fft_window,
            values=list(WINDOWS.keys()),
            width=10,
            state="readonly",
        ).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(fft_ctrl, text="dBFS", variable=self._fft_dbfs, command=self._redraw_plots).pack(
            side=tk.LEFT
        )
        ttk.Label(fft_ctrl, text="Harm").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Spinbox(fft_ctrl, from_=1, to=15, textvariable=self._n_harm, width=4).pack(side=tk.LEFT)
        ttk.Label(fft_ctrl, text="DC/F/H leak").pack(side=tk.LEFT, padx=(6, 0))
        for v in (self._dc_leak, self._fund_leak, self._harm_leak):
            ttk.Spinbox(fft_ctrl, from_=0, to=8, textvariable=v, width=3).pack(side=tk.LEFT)
        ttk.Label(fft_ctrl, text="CMRR Vin").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(fft_ctrl, textvariable=self._cmrr_amp, width=6).pack(side=tk.LEFT)
        ttk.Button(fft_ctrl, text="Apply FFT", command=self._redraw_plots).pack(side=tk.LEFT, padx=6)
        self.fft_info = tk.StringVar(value="FFT metrics: —")
        ttk.Label(self.fft_frame, textvariable=self.fft_info, wraplength=700).pack(anchor=tk.W)

        self.fig_fft = Figure(figsize=(7, 3.2), dpi=100)
        self.ax_fft = self.fig_fft.add_subplot(111)
        self.canvas_fft = FigureCanvasTkAgg(self.fig_fft, master=self.fft_frame)
        self.canvas_fft.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(self.canvas_fft, self.fft_frame)

        hist_ctrl = ttk.Frame(self.hist_frame)
        hist_ctrl.pack(fill=tk.X)
        ttk.Label(hist_ctrl, text="Bins").pack(side=tk.LEFT)
        ttk.Spinbox(hist_ctrl, from_=16, to=256, textvariable=self._hist_bins, width=5).pack(side=tk.LEFT)
        ttk.Button(hist_ctrl, text="Redraw", command=self._redraw_plots).pack(side=tk.LEFT, padx=6)
        self.fig_hist = Figure(figsize=(7, 3.6), dpi=100)
        self.ax_hist = self.fig_hist.add_subplot(111)
        self.canvas_hist = FigureCanvasTkAgg(self.fig_hist, master=self.hist_frame)
        self.canvas_hist.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(self.canvas_hist, self.hist_frame)

        cols = ("ch", "mean", "rms", "pp", "snr", "thd", "enob")
        self.stats_tree = ttk.Treeview(self.stats_frame, columns=cols, show="headings", height=12)
        for c, w in zip(cols, (50, 100, 100, 100, 80, 80, 80)):
            self.stats_tree.heading(c, text=c.upper())
            self.stats_tree.column(c, width=w, anchor=tk.CENTER)
        self.stats_tree.pack(fill=tk.BOTH, expand=True)
        self.coherent_info = tk.StringVar(value="Coherent ideal FAIN: —")
        ttk.Label(self.stats_frame, textvariable=self.coherent_info).pack(anchor=tk.W, pady=4)

        self._demo_plots()

    # --- Save -------------------------------------------------------------------
    def _build_save(self) -> None:
        f = self.tab_save
        ttk.Label(f, text="Save capture bundle", font=("Helvetica", 11, "bold")).pack(anchor=tk.W)
        row = ttk.Frame(f)
        row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="DataDir").pack(side=tk.LEFT)
        self.data_dir = tk.StringVar(value=str(Path.home() / "ads1299_captures"))
        ttk.Entry(row, textvariable=self.data_dir, width=50).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="Browse…", command=self._browse_datadir).pack(side=tk.LEFT)
        ttk.Label(f, text="Notes").pack(anchor=tk.W, pady=(8, 0))
        self.notes = tk.Text(f, height=5, width=80)
        self.notes.pack(anchor=tk.W, pady=4)
        ttk.Label(f, text="Channels to include (uses Analysis checkboxes)").pack(anchor=tk.W)
        ttk.Button(f, text="Save CSV + NPY + meta.json", command=self._save_bundle).pack(anchor=tk.W, pady=8)
        ttk.Button(f, text="Save CSV only…", command=self._save_csv_dialog).pack(anchor=tk.W, pady=2)

    # --- MMB0 -------------------------------------------------------------------
    def _build_mmb0(self) -> None:
        f = self.tab_mmb0
        ttk.Label(f, text="MMB0 clock / LED", font=("Helvetica", 11, "bold")).pack(anchor=tk.W)
        self.mmb_clkfreq = tk.StringVar(value="12000000")
        self.mmb_clkout = tk.StringVar(value="16000000")
        self.mmb_pll = tk.StringVar(value="0")
        for label, var in (
            ("/mmb0/clkfreq (Hz)", self.mmb_clkfreq),
            ("/mmb0/clkout (Hz)", self.mmb_clkout),
            ("/mmb0/pll", self.mmb_pll),
        ):
            row = ttk.Frame(f)
            row.pack(anchor=tk.W, pady=2)
            ttk.Label(row, text=label, width=22).pack(side=tk.LEFT)
            ttk.Entry(row, textvariable=var, width=16).pack(side=tk.LEFT)
        bt = ttk.Frame(f)
        bt.pack(anchor=tk.W, pady=6)
        ttk.Button(bt, text="Read MMB0", command=self._read_mmb0).pack(side=tk.LEFT, padx=4)
        ttk.Button(bt, text="Write clkfreq/pll/clkout", command=self._write_mmb0).pack(side=tk.LEFT, padx=4)

        led = ttk.LabelFrame(f, text="LED (/mmb0/led/*)", padding=8)
        led.pack(fill=tk.X, pady=12)
        self.led_dp = tk.StringVar(value="0")
        self.led_seg = tk.StringVar(value="0")
        self.led_ch = tk.StringVar(value="0")
        for label, var in (("dp", self.led_dp), ("seg", self.led_seg), ("ch", self.led_ch)):
            row = ttk.Frame(led)
            row.pack(anchor=tk.W)
            ttk.Label(row, text=label, width=6).pack(side=tk.LEFT)
            ttk.Entry(row, textvariable=var, width=10).pack(side=tk.LEFT)
        ttk.Button(led, text="Write LEDs", command=self._write_leds).pack(anchor=tk.W, pady=4)

    # --- helpers ----------------------------------------------------------------
    def _sync_vref_gain(self) -> None:
        self.session.vref = float(self.vref_var.get())
        self.session.gain = float(self.gain_var.get())

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        conn = tk.DISABLED if busy or self.session.connected else tk.NORMAL
        disc = tk.DISABLED if busy or not self.session.connected else tk.NORMAL
        linked = tk.DISABLED if busy or not self.session.connected else tk.NORMAL
        self.conn_btn.configure(state=conn)
        self.disc_btn.configure(state=disc)
        self.refresh_btn.configure(state=linked)
        self.acq_btn.configure(state=linked)
        self.loff_btn.configure(state=linked)
        streaming = getattr(self, "_streaming", False)
        self.stream_btn.configure(
            state=tk.DISABLED if busy or not self.session.connected or streaming else tk.NORMAL
        )
        self.stream_stop_btn.configure(
            state=tk.NORMAL if streaming else tk.DISABLED
        )

    def _ui(self, fn: Callable) -> None:
        self.after(0, fn)

    def _poll_usb(self) -> None:
        if not self.session.connected:
            self.status.set(f"Disconnected — USB {self.session.usb_status()}")
        else:
            # Refresh progress bar leftover
            self.progress["value"] = self.session.progress_frac * 100
        self.after(500, self._poll_usb)

    def _run_bg(self, work: Callable, done: Callable | None = None) -> None:
        if self._busy:
            return

        def runner():
            err = None
            result = None
            try:
                result = work()
            except Exception as e:
                err = e

            def finish():
                self._set_busy(False)
                self.progress["value"] = 100 if err is None else 0
                if err is not None:
                    self.status.set(str(err))
                    messagebox.showerror("ADS1299", str(err))
                elif done:
                    done(result)

            self._ui(finish)

        self._set_busy(True)
        threading.Thread(target=runner, daemon=True).start()

    def _connect(self) -> None:
        def work():
            def tick():
                self.progress["value"] = self.session.progress_frac * 100
                self.status.set(self.session.progress_text or "Connecting…")
                if self._busy:
                    self.after(200, tick)

            self._ui(tick)
            return self.session.connect()

        def done(detail):
            self.about_info.set(f"Device: {detail}")
            self.status.set(f"Connected — {detail}")
            self.progress["value"] = 100
            self._read_regs()
            self._read_mmb0()

        self.status.set("Connecting / loading firmware…")
        self._run_bg(work, done)

    def _disconnect(self) -> None:
        self.session.disconnect()
        self.about_info.set("Device: (not connected)")
        self.status.set("Disconnected")
        self.progress["value"] = 0
        self._set_busy(False)

    def _write_reg(self, styx: str, value: int) -> None:
        if not self.session.connected:
            messagebox.showwarning("ADS1299", "Connect first")
            return

        def work():
            self.session.write_register(styx, value)
            return styx, value

        def done(pair):
            k, v = pair
            if k in self._hex:
                self._hex[k].set_value(v)
            if k in self.reg_tree.get_children():
                vals = list(self.reg_tree.item(k, "values"))
                vals[3] = f"0x{v:02X}"
                self.reg_tree.item(k, values=vals)
            self._sync_bit_widgets_from_hex(k, v)
            self.status.set(f"Wrote {k}=0x{v:02X}")

        self._run_bg(work, done)

    def _sync_bit_widgets_from_hex(self, styx: str, val: int) -> None:
        if styx == "config1":
            self.cfg1_daisy.set(bool(val & 0x40))
            self.cfg1_clken.set(bool(val & 0x20))
            self.dr_var.set(DR_LABELS.get(val & 7, "250 SPS"))
        elif styx == "config2":
            self.cfg2_intcal.set(bool(val & 0x10))
            self.cfg2_calamp.set(bool(val & 0x04))
            self.cfg2_calfreq.set(val & 3)
        elif styx == "config3":
            self.cfg3_refbuf.set(bool(val & 0x80))
            self.cfg3_biasmeas.set(bool(val & 0x10))
            self.cfg3_biasref.set(bool(val & 0x08))
            self.cfg3_pdbias.set(bool(val & 0x04))
        elif styx == "config4":
            self.cfg4_pdloff.set(bool(val & 0x02))
        elif styx == "gpio":
            for i in range(4):
                self.gpio_data[i].set(bool((val >> (4 + i)) & 1))
                self.gpio_ctrl[i].set(bool((val >> i) & 1))
        elif styx == "misc1":
            self.srb1.set(bool(val & 0x20))

    def _read_regs(self) -> None:
        def work():
            return self.session.read_all_registers()

        def done(regs: dict):
            for styx, val in regs.items():
                if styx in self._hex:
                    self._hex[styx].set_value(val)
                if styx in self.reg_tree.get_children():
                    vals = list(self.reg_tree.item(styx, "values"))
                    vals[3] = f"0x{val:02X}"
                    self.reg_tree.item(styx, values=vals)
                if styx.startswith("ch") and styx.endswith("set"):
                    self._decode_ch_widgets(int(styx[2]) - 1, val)
                self._sync_bit_widgets_from_hex(styx, val)
            self.status.set("Registers refreshed")

        self._run_bg(work, done)

    def _decode_ch_widgets(self, idx: int, val: int) -> None:
        inv_gain = {v: k for k, v in GAIN.items()}
        inv_mux = {v: k for k, v in MUX.items()}
        self._ch_gain[idx].set(inv_gain.get((val >> 4) & 7, 24))
        self._ch_mux[idx].set(inv_mux.get(val & 7, "normal"))
        self._ch_pd[idx].set(bool(val & 0x80))
        self._ch_srb2[idx].set(bool(val & 0x08))

    def _apply_one_ch(self, idx: int) -> None:
        self._write_reg(
            f"ch{idx+1}set",
            chset(
                gain=int(self._ch_gain[idx].get()),
                mux=self._ch_mux[idx].get(),
                pd=self._ch_pd[idx].get(),
                srb2=self._ch_srb2[idx].get(),
            ),
        )

    def _apply_all_ch(self) -> None:
        for i in range(8):
            self._ch_gain[i].set(int(self.all_gain.get()))
            self._ch_mux[i].set(self.all_mux.get())
            self._apply_one_ch(i)

    def _apply_config1(self) -> None:
        dr = next(k for k, v in DR_LABELS.items() if v == self.dr_var.get())
        self._write_reg(
            "config1",
            pack_config1(daisy=self.cfg1_daisy.get(), clk_en=self.cfg1_clken.get(), dr=dr),
        )

    def _apply_config2(self) -> None:
        self._write_reg(
            "config2",
            pack_config2(
                int_cal=self.cfg2_intcal.get(),
                cal_amp=self.cfg2_calamp.get(),
                cal_freq=int(self.cfg2_calfreq.get()),
            ),
        )

    def _apply_config3(self) -> None:
        self._write_reg(
            "config3",
            pack_config3(
                pd_refbuf=self.cfg3_refbuf.get(),
                bias_meas=self.cfg3_biasmeas.get(),
                biasref_int=self.cfg3_biasref.get(),
                pd_bias=self.cfg3_pdbias.get(),
            ),
        )

    def _apply_config4(self) -> None:
        self._write_reg("config4", pack_config4(pd_loff_comp=self.cfg4_pdloff.get()))

    def _apply_gpio(self) -> None:
        data = sum((1 << i) for i, v in enumerate(self.gpio_data) if v.get())
        ctrl = sum((1 << i) for i, v in enumerate(self.gpio_ctrl) if v.get())
        self._write_reg("gpio", pack_gpio(data=data, control=ctrl))

    def _apply_srb1(self) -> None:
        try:
            current = self._hex["misc1"].get_value()
        except Exception:
            current = 0
        current = (current | 0x20) if self.srb1.get() else (current & ~0x20)
        self._write_reg("misc1", current)

    def _open_loff_dialog(self) -> None:
        if not self.session.connected:
            messagebox.showwarning("Lead-Off", "Connect first")
            return
        win = tk.Toplevel(self)
        win.title("Lead-Off Status (poll)")
        win.geometry("420x220")
        canvas = tk.Canvas(win, width=400, height=160, bg="#222")
        canvas.pack(padx=8, pady=8)
        info = tk.StringVar(value="")
        ttk.Label(win, textvariable=info).pack()
        polling = {"on": True}

        def paint(p: int, n: int) -> None:
            canvas.delete("all")
            pb, nb = lead_off_bits(p), lead_off_bits(n)
            # True = connected (bit high) → green
            for i in range(8):
                canvas.create_oval(
                    20 + i * 45, 30, 50 + i * 45, 60, fill=("#2ecc71" if pb[i] else "#e74c3c")
                )
                canvas.create_text(35 + i * 45, 75, text=f"P{i+1}", fill="white")
                canvas.create_oval(
                    20 + i * 45, 100, 50 + i * 45, 130, fill=("#2ecc71" if nb[i] else "#e74c3c")
                )
                canvas.create_text(35 + i * 45, 145, text=f"N{i+1}", fill="white")
            info.set(f"loffstatp=0x{p:02X}  loffstatn=0x{n:02X}  (green=connected)")

        def tick():
            if not polling["on"] or not win.winfo_exists():
                return
            try:
                p, n = self.session.poll_lead_off()
                paint(p, n)
            except Exception as e:
                info.set(str(e))
            win.after(500, tick)

        def stop():
            polling["on"] = False
            win.destroy()

        ttk.Button(win, text="Close", command=stop).pack(pady=4)
        win.protocol("WM_DELETE_WINDOW", stop)
        tick()

    def _run_preset(self, key: str) -> None:
        if not self.session.connected:
            messagebox.showwarning("Preset", "Connect first")
            return

        def work():
            return self.session.apply_preset(key)

        def done(msg):
            self.status.set(msg)
            self._read_regs()
            # Auto-acquire after preset
            self._acquire()

        self._run_bg(work, done)

    def _acquire(self) -> None:
        self._sync_vref_gain()
        n = int(self.n_samples.get())

        def work():
            return self.session.capture(n)

        def done(result):
            volts, codes, msg = result
            self.status.set(msg)
            if volts is None:
                messagebox.showwarning("Acquire", msg)
                return
            self._redraw_plots()

        self.status.set("Acquiring…")
        self._run_bg(work, done)

    def _stream_start(self) -> None:
        if getattr(self, "_streaming", False):
            return
        self._sync_vref_gain()
        chunk = max(1, int(self.chunk_frames.get()))
        dur = float(self.stream_duration.get())
        duration_s = dur if dur > 0 else None
        self._streaming = True
        self._set_busy(True)
        self.stream_status.set("Streaming…")
        self.status.set("Segmented continuous capture…")

        def on_block(_block):
            def ui():
                self.stream_status.set(
                    f"frames={self.session.stream_frames}  "
                    f"blocks={self.session.stream_blocks}  "
                    f"gap={self.session.stream_last_gap_ms:.0f} ms"
                )
                # Rolling scope preview
                roll = self.session.rolling_volts
                if roll is not None:
                    saved = self.session.last_volts
                    self.session.last_volts = roll
                    try:
                        self._redraw_scope_only()
                    finally:
                        if saved is not None:
                            self.session.last_volts = saved

            self._ui(ui)

        def work():
            return self.session.run_continuous(
                chunk_frames=chunk, duration_s=duration_s, on_block=on_block
            )

        def runner():
            err = None
            result = None
            try:
                result = work()
            except Exception as e:
                err = e

            def finish():
                self._streaming = False
                self._set_busy(False)
                if err is not None:
                    self.stream_status.set(str(err))
                    self.status.set(str(err))
                    messagebox.showerror("Continuous", str(err))
                    return
                self.stream_status.set(result)
                self.status.set(result)
                self._redraw_plots()

            self._ui(finish)

        threading.Thread(target=runner, daemon=True).start()

    def _stream_stop(self) -> None:
        self.session.stream_stop.set()
        self.stream_status.set("Stopping after current block…")

    def _redraw_scope_only(self) -> None:
        volts = self.session.last_volts
        if volts is None:
            return
        self.ax_scope.clear()
        zoom = self._scope_zoom_ch.get()
        chans = self._enabled_indices()
        if zoom.startswith("CH"):
            only = int(zoom[2:]) - 1
            chans = [only] if only in chans else chans
        x = np.arange(volts.shape[0])
        for i in chans:
            if i < volts.shape[1]:
                self.ax_scope.plot(x, volts[:, i], color=CH_COLORS[i], lw=1.0, label=f"CH{i+1}")
        self.ax_scope.set_title(
            f"Scope (rolling) frames={self.session.stream_frames} "
            f"gap={self.session.stream_last_gap_ms:.0f}ms"
        )
        self.ax_scope.grid(True, alpha=0.3)
        self.ax_scope.legend(loc="upper right", fontsize=8)
        self.fig_scope.tight_layout()
        self.canvas_scope.draw_idle()

    def _demo_plots(self) -> None:
        t = np.arange(256)
        demo = np.stack([0.00005 * np.sin(2 * np.pi * (i + 1) * t / 256) for i in range(8)], axis=1)
        self.session.last_volts = demo
        self.session.last_codes = (demo / ((2 * 4.5 / 24) / 2**24)).astype(np.int32)
        self.session.last_sps = 250.0
        self._redraw_plots()
        self.ax_scope.set_title("Scope (demo — connect & Acquire for live data)")
        self.canvas_scope.draw_idle()

    def _enabled_indices(self) -> list[int]:
        return [i for i in range(8) if self._ch_enabled[i].get()]

    def _redraw_plots(self) -> None:
        volts = self.session.last_volts
        if volts is None:
            return
        self._sync_vref_gain()
        sps = float(self.session.last_sps or 250.0)
        fs_full = float(self.session.vref) / max(float(self.session.gain), 1e-12)

        # Scope
        self.ax_scope.clear()
        zoom = self._scope_zoom_ch.get()
        chans = self._enabled_indices()
        if zoom.startswith("CH"):
            only = int(zoom[2:]) - 1
            chans = [only] if only in chans else chans
        x = np.arange(volts.shape[0])
        for i in chans:
            if i < volts.shape[1]:
                self.ax_scope.plot(x, volts[:, i], color=CH_COLORS[i], lw=1.0, label=f"CH{i+1}")
        self.ax_scope.set_xlabel("Sample")
        self.ax_scope.set_ylabel("Volts")
        self.ax_scope.set_title(f"Scope  sps={sps:.0f}  gain={self.session.gain:g}  Vref={self.session.vref:g}")
        self.ax_scope.grid(True, alpha=0.3)
        self.ax_scope.legend(loc="upper right", fontsize=8)
        self.fig_scope.tight_layout()
        self.canvas_scope.draw_idle()

        # FFT
        self.ax_fft.clear()
        params = AcParams(
            n_harmonics=int(self._n_harm.get()),
            dc_leak_bins=int(self._dc_leak.get()),
            fund_leak_bins=int(self._fund_leak.get()),
            harm_leak_bins=int(self._harm_leak.get()),
        )
        metrics_lines = []
        n = volts.shape[0]
        ideal = coherent_ideal_freq(sps, n, n_cycles=1)
        self.coherent_info.set(
            f"Coherent ideal FAIN ≈ {ideal:.6f} Hz  (fs={sps:.1f}, N={n}, odd cycles=1)"
        )
        for i in chans:
            if i >= volts.shape[1]:
                continue
            y = volts[:, i]
            freqs, mag = rfft_db(
                y, fs=sps, window=self._fft_window.get(), dbfs=self._fft_dbfs.get(), full_scale=fs_full
            )
            self.ax_fft.plot(freqs, mag, color=CH_COLORS[i], lw=1.0, label=f"CH{i+1}")
            m = fft_metrics(y, fs=sps, window=self._fft_window.get(), params=params)
            cmrr = cmrr_db(self._cmrr_amp.get(), m.fund_db and (10 ** (m.fund_db / 20)) or 1e-6)
            # Better CMRR: use RMS of channel as common-mode residual vs user amp
            cmrr = cmrr_db(self._cmrr_amp.get(), float(np.sqrt(np.mean(y * y))) or 1e-12)
            metrics_lines.append(
                f"CH{i+1}: SNR={m.snr_db:.1f}dB THD={m.thd_db:.1f}dB ENOB={m.enob:.2f} "
                f"f0={m.fund_hz:.2f}Hz CMRR≈{cmrr:.1f}dB"
            )
        self.ax_fft.set_xlabel("Hz")
        self.ax_fft.set_ylabel("dBFS" if self._fft_dbfs.get() else "dB")
        self.ax_fft.grid(True, alpha=0.3)
        self.ax_fft.legend(loc="upper right", fontsize=8)
        self.fig_fft.tight_layout()
        self.canvas_fft.draw_idle()
        self.fft_info.set(" | ".join(metrics_lines) if metrics_lines else "FFT metrics: —")

        # Histogram
        self.ax_hist.clear()
        bins = int(self._hist_bins.get())
        for i in chans:
            if i < volts.shape[1]:
                self.ax_hist.hist(
                    volts[:, i], bins=bins, alpha=0.35, color=CH_COLORS[i], label=f"CH{i+1}"
                )
        self.ax_hist.set_xlabel("Volts")
        self.ax_hist.set_ylabel("Count")
        self.ax_hist.grid(True, alpha=0.3)
        self.ax_hist.legend(loc="upper right", fontsize=8)
        self.fig_hist.tight_layout()
        self.canvas_hist.draw_idle()

        # Analysis table
        for item in self.stats_tree.get_children():
            self.stats_tree.delete(item)
        stats = channel_stats(volts)
        for i, st in enumerate(stats):
            if i not in chans:
                continue
            m = fft_metrics(volts[:, i], fs=sps, window=self._fft_window.get(), params=params)
            self.stats_tree.insert(
                "",
                tk.END,
                values=(
                    f"CH{i+1}",
                    f"{st.mean:.3e}",
                    f"{st.rms:.3e}",
                    f"{st.peak_peak:.3e}",
                    f"{m.snr_db:.2f}",
                    f"{m.thd_db:.2f}",
                    f"{m.enob:.2f}",
                ),
            )

    def _browse_datadir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.data_dir.set(path)

    def _save_bundle(self) -> None:
        try:
            stem = self.session.save_bundle(
                self.data_dir.get(),
                notes=self.notes.get("1.0", tk.END).strip(),
                channels=[v.get() for v in self._ch_enabled],
            )
            self.status.set(f"Saved bundle {stem}.*")
        except Exception as e:
            messagebox.showerror("Save", str(e))

    def _save_csv_dialog(self) -> None:
        volts = self.session.last_volts
        if volts is None:
            messagebox.showinfo("Save", "No capture yet")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        idx = self._enabled_indices() or list(range(volts.shape[1]))
        import csv

        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["sample"] + [f"ch{i+1}" for i in idx])
            for i, row in enumerate(volts[:, idx]):
                w.writerow([i, *[f"{v:.10e}" for v in row]])
        self.status.set(f"Saved {path}")

    def _read_mmb0(self) -> None:
        if not self.session.connected:
            return

        def work():
            return {
                "clkfreq": self.session.read_path("/mmb0/clkfreq"),
                "clkout": self.session.read_path("/mmb0/clkout"),
                "pll": self.session.read_path("/mmb0/pll"),
            }

        def done(d):
            self.mmb_clkfreq.set(d["clkfreq"])
            self.mmb_clkout.set(d["clkout"])
            self.mmb_pll.set(d["pll"])
            self.status.set("MMB0 clock paths read")

        self._run_bg(work, done)

    def _write_mmb0(self) -> None:
        if not self.session.connected:
            messagebox.showwarning("MMB0", "Connect first")
            return

        def work():
            self.session.write_path("/mmb0/clkfreq", self.mmb_clkfreq.get().strip())
            self.session.write_path("/mmb0/pll", self.mmb_pll.get().strip())
            # clkout is frequency Hz — write only if user changed intentionally
            self.session.write_path("/mmb0/clkout", self.mmb_clkout.get().strip())
            return True

        def done(_):
            self.status.set("Wrote /mmb0/clkfreq, pll, clkout")

        self._run_bg(work, done)

    def _write_leds(self) -> None:
        if not self.session.connected:
            return

        def work():
            self.session.write_path("/mmb0/led/dp", self.led_dp.get().strip())
            self.session.write_path("/mmb0/led/seg", self.led_seg.get().strip())
            self.session.write_path("/mmb0/led/ch", self.led_ch.get().strip())
            return True

        def done(_):
            self.status.set("Wrote LED paths")

        self._run_bg(work, done)

    def _on_close(self) -> None:
        try:
            self.session.disconnect()
        except Exception:
            pass
        self.destroy()


def run_gui() -> None:
    MainApp().mainloop()


def main() -> None:
    run_gui()


if __name__ == "__main__":
    main()
