#!/usr/bin/env python3
"""Launch the ADS1299 GUI and capture every notebook page for docs."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from PIL import ImageGrab

# Ensure package import from repo root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ads1299_mmb0.gui.app import MainApp  # noqa: E402

OUT = ROOT / "docs" / "gui_screenshots" / "_live"
OUT.mkdir(parents=True, exist_ok=True)


def _grab(app: MainApp, stem: str) -> Path:
    app.update_idletasks()
    app.update()
    time.sleep(0.35)
    # Prefer crisp macOS window capture when available
    title = app.title()
    png = OUT / f"{stem}.png"
    try:
        script = f'''
        tell application "System Events"
          set procs to every process whose name is "Python" or name is "python" or name is "python3"
          repeat with p in procs
            repeat with w in (windows of p)
              try
                if name of w contains "ADS1299" then
                  set {{x, y}} to position of w
                  set {{ww, hh}} to size of w
                  return (x as text) & "," & (y as text) & "," & (ww as text) & "," & (hh as text)
                end if
              end try
            end repeat
          end repeat
        end tell
        return ""
        '''
        r = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, check=False
        )
        geom = r.stdout.strip()
        if geom and "," in geom:
            x, y, ww, hh = [int(float(v)) for v in geom.split(",")]
            # screencapture -R is x,y,w,h in points
            subprocess.run(
                ["screencapture", "-x", "-R", f"{x},{y},{ww},{hh}", str(png)],
                check=True,
            )
            if png.exists() and png.stat().st_size > 1000:
                print(f"saved {png.name} ({png.stat().st_size} bytes) via screencapture")
                return png
    except Exception as e:
        print(f"screencapture fallback for {stem}: {e}")

    # Pillow fallback (may be low-DPI / include chrome)
    x = app.winfo_rootx()
    y = app.winfo_rooty()
    w = app.winfo_width()
    h = app.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    img.save(png)
    print(f"saved {png.name} ({png.stat().st_size} bytes) via ImageGrab")
    return png


def _select_tab(notebook, text: str) -> None:
    for i in range(notebook.index("end")):
        if notebook.tab(i, "text") == text:
            notebook.select(i)
            return
    raise KeyError(text)


def main() -> int:
    app = MainApp()
    app.update_idletasks()
    app.lift()
    app.attributes("-topmost", True)
    app.after(200, lambda: app.attributes("-topmost", False))
    app.update()
    time.sleep(0.8)

    shots: list[tuple[str, str]] = []

    # Main tabs
    _select_tab(app.notebook, "About")
    _grab(app, "01-about")
    shots.append(("01-about.png", "About — product intro, USB IDs, connection status"))

    _select_tab(app.notebook, "ADC Registers")
    reg_nb = None
    for child in app.tab_regs.winfo_children():
        if child.winfo_class() == "TNotebook":
            reg_nb = child
            break
    assert reg_nb is not None
    for idx, name in enumerate(
        ["Global", "Channels", "LOFF & BIAS", "GPIO / Other", "Register Map"], start=2
    ):
        _select_tab(reg_nb, name)
        stem = f"{idx:02d}-registers-{name.lower().replace(' ', '-').replace('&', 'and')}"
        _grab(app, stem)
        shots.append((f"{stem}.png", f"ADC Registers → {name}"))

    _select_tab(app.notebook, "Analysis")
    an_nb = None
    for child in app.tab_analysis.winfo_children():
        if child.winfo_class() == "TNotebook":
            an_nb = child
            break
    # Analysis notebook is nested in the right pane
    if an_nb is None:
        for child in app.tab_analysis.winfo_children():
            for g in child.winfo_children():
                if g.winfo_class() == "TNotebook":
                    an_nb = g
                    break
    assert an_nb is not None
    for idx, name in enumerate(["Scope", "FFT", "Histogram", "Analysis"], start=7):
        _select_tab(an_nb, name)
        stem = f"{idx:02d}-analysis-{name.lower()}"
        _grab(app, stem)
        shots.append((f"{stem}.png", f"Analysis → {name} (demo waveform until Acquire)"))

    _select_tab(app.notebook, "Save")
    _grab(app, "11-save")
    shots.append(("11-save.png", "Save — CSV / NPY / meta.json capture bundle"))

    _select_tab(app.notebook, "MMB0")
    _grab(app, "12-mmb0")
    shots.append(("12-mmb0.png", "MMB0 — clock / PLL / LED Styx paths"))

    # Manifest for docs
    manifest = OUT / "MANIFEST.md"
    lines = ["# GUI screenshot manifest", "", "| File | Description |", "|------|-------------|"]
    for fn, desc in shots:
        lines.append(f"| `{fn}` | {desc} |")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {manifest}")

    app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
