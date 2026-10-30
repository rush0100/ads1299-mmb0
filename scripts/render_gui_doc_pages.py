#!/usr/bin/env python3
"""Render HTML documentation pages that mirror the live GUI, then screenshot with Chrome."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "docs" / "gui_html"
SHOTS = ROOT / "docs" / "gui_screenshots"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

PAGES = [
    (
        "01-about",
        "About",
        None,
        """
        <h1>EEG Front-End Performance Demonstration Kit</h1>
        <p>Python EVM client — functional parity with SLAU443B LabVIEW software
        (registers, lead-off poll, scope/FFT/histogram/analysis, impedance presets, save).</p>
        <p>Block capture only (MMB0 buffer-then-USB). Eval/lab use — not for diagnosis.</p>
        <p>Impedance presets need matching jumpers (JP25/J6) per User Guide.</p>
        <p><b>Device:</b> (not connected)</p>
        <p class="muted">USB IDs: boot 0x0451:0x9001 → styx 0x0451:0x5718</p>
        <div class="note">Launch with <code>ads1299-gui</code>. Connect loads firmware if the board is in bootloader mode.</div>
        """,
    ),
    (
        "02-registers-global",
        "ADC Registers",
        "Global",
        """
        <div class="subtabs"><span class="on">Global</span><span>Channels</span><span>LOFF &amp; BIAS</span><span>GPIO / Other</span><span>Register Map</span></div>
        <h2>CONFIG bit fields</h2>
        <div class="panel">
          <b>CONFIG1</b>
          <div class="row"><span class="check">☐ DAISY_EN</span><span class="check">☑ CLK_EN</span>
            DR <span class="field">250 SPS</span> <span class="btn">Apply CONFIG1</span></div>
        </div>
        <div class="panel">
          <b>CONFIG2</b>
          <div class="row"><span class="check">☐ INT_CAL</span><span class="check">☐ CAL_AMP</span>
            CAL_FREQ <span class="field">0</span> <span class="btn">Apply CONFIG2</span></div>
        </div>
        <div class="panel">
          <b>CONFIG3</b>
          <div class="row"><span class="check">☑ PD_REFBUF on</span><span class="check">☐ BIAS_MEAS</span>
            <span class="check">☑ BIASREF_INT</span><span class="check">☑ PD_BIAS on</span>
            <span class="btn">Apply CONFIG3</span></div>
        </div>
        <div class="panel">
          <b>CONFIG4 / LOFF hex</b>
          <div class="row"><span class="check">☐ PD_LOFF_COMP</span> <span class="btn">Apply CONFIG4</span></div>
        </div>
        <h2>Advanced hex</h2>
        <div class="row">CONFIG1 <span class="field">0x96</span> <span class="btn">Set</span></div>
        <div class="row">CONFIG2 <span class="field">0xC0</span> <span class="btn">Set</span></div>
        <div class="row">CONFIG3 <span class="field">0xE0</span> <span class="btn">Set</span></div>
        <div class="row"><span class="btn">Software Reset</span><span class="btn">Sleep</span><span class="btn">Wake</span></div>
        """,
    ),
    (
        "03-registers-channels",
        "ADC Registers",
        "Channels",
        """
        <div class="subtabs"><span>Global</span><span class="on">Channels</span><span>LOFF &amp; BIAS</span><span>GPIO / Other</span><span>Register Map</span></div>
        <div class="row">Apply all → <span class="field">24</span> <span class="field">normal</span> <span class="btn">Set all channels</span></div>
        <table>
          <tr><th>CH</th><th>Gain</th><th>MUX</th><th>PD</th><th>SRB2</th><th>Hex</th><th></th></tr>
          {rows}
        </table>
        """.format(
            rows="\n".join(
                f"<tr><td>{i}</td><td>24</td><td>normal</td><td>☐</td><td>☐</td>"
                f"<td>0x60</td><td><span class='btn'>Apply</span></td></tr>"
                for i in range(1, 9)
            )
        ),
    ),
    (
        "04-registers-loff-and-bias",
        "ADC Registers",
        "LOFF & BIAS",
        """
        <div class="subtabs"><span>Global</span><span>Channels</span><span class="on">LOFF &amp; BIAS</span><span>GPIO / Other</span><span>Register Map</span></div>
        <div class="row">LOFFSENS P <span class="field">0x00</span> <span class="btn">Set</span></div>
        <div class="row">LOFFSENS N <span class="field">0x00</span> <span class="btn">Set</span></div>
        <div class="row">LOFFFLIP <span class="field">0x00</span> <span class="btn">Set</span></div>
        <div class="row">LOFFSTAT P <span class="field">0x00</span> <span class="btn">Set</span></div>
        <div class="row">LOFFSTAT N <span class="field">0x00</span> <span class="btn">Set</span></div>
        <div class="row">BIASSENS P <span class="field">0x00</span> <span class="btn">Set</span></div>
        <div class="row">BIASSENS N <span class="field">0x00</span> <span class="btn">Set</span></div>
        <div class="row" style="margin-top:12px"><span class="btn">Show/Poll Lead-Off Status…</span></div>
        <div class="note">Lead-Off dialog polls <code>loffstatp/n</code> every 500 ms (green = connected).</div>
        """,
    ),
    (
        "05-registers-gpio-other",
        "ADC Registers",
        "GPIO / Other",
        """
        <div class="subtabs"><span>Global</span><span>Channels</span><span>LOFF &amp; BIAS</span><span class="on">GPIO / Other</span><span>Register Map</span></div>
        <div class="panel">
          <b>GPIO (data[7:4] / ctrl[3:0]=1 output)</b>
          <div class="row">DATA ☐ D1 ☐ D2 ☐ D3 ☐ D4</div>
          <div class="row">CTRL ☐ C1 ☐ C2 ☐ C3 ☐ C4</div>
          <span class="btn">Apply GPIO</span>
        </div>
        <div class="row">GPIO <span class="field">0x00</span> <span class="btn">Set</span></div>
        <div class="row">MISC1 <span class="field">0x00</span> <span class="btn">Set</span></div>
        <div class="row">MISC2 <span class="field">0x00</span> <span class="btn">Set</span></div>
        <div class="row">DEVID <span class="field">0x3E</span> <span class="btn">Set</span></div>
        <div class="row"><span class="check">☐ SRB1 enable (MISC1 bit5)</span></div>
        """,
    ),
    (
        "06-registers-register-map",
        "ADC Registers",
        "Register Map",
        """
        <div class="subtabs"><span>Global</span><span>Channels</span><span>LOFF &amp; BIAS</span><span>GPIO / Other</span><span class="on">Register Map</span></div>
        <table>
          <tr><th>ADDR</th><th>NAME</th><th>STYX</th><th>VALUE</th></tr>
          <tr><td>0x00</td><td>ID</td><td>devid</td><td>—</td></tr>
          <tr><td>0x01</td><td>CONFIG1</td><td>config1</td><td>—</td></tr>
          <tr><td>0x02</td><td>CONFIG2</td><td>config2</td><td>—</td></tr>
          <tr><td>0x03</td><td>CONFIG3</td><td>config3</td><td>—</td></tr>
          <tr><td>0x04</td><td>LOFF</td><td>loff</td><td>—</td></tr>
          <tr><td>0x05</td><td>CH1SET</td><td>ch1set</td><td>—</td></tr>
          <tr><td>…</td><td>…</td><td>…</td><td>—</td></tr>
          <tr><td>0x17</td><td>CONFIG4</td><td>config4</td><td>—</td></tr>
        </table>
        <p class="small">Values fill after <b>Read Registers</b> / Connect.</p>
        """,
    ),
    (
        "07-analysis-scope",
        "Analysis",
        "Scope",
        """
        <div class="grid cols-2">
          <div>
            <h2>Capture</h2>
            <div>Frames <span class="field">1024</span></div>
            <div>Vref <span class="field">4.5</span></div>
            <div>Gain <span class="field">24</span></div>
            <div class="row"><span class="btn">Acquire</span></div>
            <div class="panel">
              <b>Continuous (segmented)</b>
              <div>Chunk frames <span class="field">256</span></div>
              <div>Duration s <span class="field">0</span></div>
              <div class="row"><span class="btn">Start</span><span class="btn">Stop</span></div>
              <div class="small">Idle (not zero-gap USB)</div>
            </div>
            <h2>Presets</h2>
            <div class="btn" style="display:block;margin:3px 0">Input short noise</div>
            <div class="btn" style="display:block;margin:3px 0">Internal test signal</div>
            <div class="btn" style="display:block;margin:3px 0">Impedance @ 31.2 Hz</div>
            <div class="btn" style="display:block;margin:3px 0">Impedance @ fDR/4</div>
            <div class="small">Channels CH1…CH8 · Scope zoom · Redraw</div>
          </div>
          <div>
            <div class="subtabs"><span class="on">Scope</span><span>FFT</span><span>Histogram</span><span>Analysis</span></div>
            <img class="plot" src="../gui_screenshots/plot-scope-demo.png" alt="scope"/>
          </div>
        </div>
        """,
    ),
    (
        "08-analysis-fft",
        "Analysis",
        "FFT",
        """
        <div class="grid cols-2">
          <div>
            <h2>Capture / Presets</h2>
            <div class="btn" style="display:block;margin:3px 0">Acquire</div>
            <div class="btn" style="display:block;margin:3px 0">Input short noise</div>
            <div class="btn" style="display:block;margin:3px 0">Internal test signal</div>
            <p class="small">Same left rail as Scope tab.</p>
          </div>
          <div>
            <div class="subtabs"><span>Scope</span><span class="on">FFT</span><span>Histogram</span><span>Analysis</span></div>
            <div class="row">Window <span class="field">hann</span> ☑ dBFS Harm <span class="field">5</span>
              DC/F/H leak <span class="field">1</span><span class="field">1</span><span class="field">1</span>
              CMRR Vin <span class="field">1.0</span> <span class="btn">Apply FFT</span></div>
            <p class="small">FFT metrics: SNR / THD / ENOB / f0 / CMRR per enabled channel</p>
            <img class="plot" src="../gui_screenshots/plot-fft-demo.png" alt="fft" style="height:320px"/>
          </div>
        </div>
        """,
    ),
    (
        "09-analysis-histogram",
        "Analysis",
        "Histogram",
        """
        <div class="grid cols-2">
          <div>
            <h2>Capture</h2>
            <div class="btn">Acquire</div>
            <p class="small">Histogram uses last capture volts.</p>
          </div>
          <div>
            <div class="subtabs"><span>Scope</span><span>FFT</span><span class="on">Histogram</span><span>Analysis</span></div>
            <div class="row">Bins <span class="field">64</span> <span class="btn">Redraw</span></div>
            <img class="plot" src="../gui_screenshots/plot-hist-demo.png" alt="hist"/>
          </div>
        </div>
        """,
    ),
    (
        "10-analysis-analysis",
        "Analysis",
        "Analysis",
        """
        <div class="grid cols-2">
          <div>
            <h2>Capture</h2>
            <div class="btn">Acquire</div>
          </div>
          <div>
            <div class="subtabs"><span>Scope</span><span>FFT</span><span>Histogram</span><span class="on">Analysis</span></div>
            <table>
              <tr><th>CH</th><th>MEAN</th><th>RMS</th><th>PP</th><th>SNR</th><th>THD</th><th>ENOB</th></tr>
              <tr><td>CH1</td><td>0.000e+00</td><td>3.5e-05</td><td>1.0e-04</td><td>—</td><td>—</td><td>—</td></tr>
              <tr><td>CH2</td><td>0.000e+00</td><td>3.5e-05</td><td>1.0e-04</td><td>—</td><td>—</td><td>—</td></tr>
              <tr><td colspan="7">… CH3–CH8 …</td></tr>
            </table>
            <p class="small">Coherent ideal FAIN ≈ f(fs, N, odd cycles)</p>
          </div>
        </div>
        """,
    ),
    (
        "11-save",
        "Save",
        None,
        """
        <h1>Save capture bundle</h1>
        <div class="row">DataDir <span class="field" style="min-width:360px">~/ads1299_captures</span> <span class="btn">Browse…</span></div>
        <h2>Notes</h2>
        <div class="panel" style="min-height:90px;background:#fff">Optional experiment notes…</div>
        <p>Channels to include (uses Analysis checkboxes)</p>
        <div class="row"><span class="btn">Save CSV + NPY + meta.json</span></div>
        <div class="row"><span class="btn">Save CSV only…</span></div>
        <div class="note">Bundle writes volts/codes plus JSON metadata (sps, gain, Vref, notes).</div>
        """,
    ),
    (
        "12-mmb0",
        "MMB0",
        None,
        """
        <h1>MMB0 clock / LED</h1>
        <div class="row">/mmb0/clkfreq (Hz) <span class="field">12000000</span></div>
        <div class="row">/mmb0/clkout (Hz) <span class="field">16000000</span></div>
        <div class="row">/mmb0/pll <span class="field">0</span></div>
        <div class="row"><span class="btn">Read MMB0</span><span class="btn">Write clkfreq/pll/clkout</span></div>
        <div class="panel" style="margin-top:16px">
          <b>LED (/mmb0/led/*)</b>
          <div class="row">dp <span class="field">0</span></div>
          <div class="row">seg <span class="field">0</span></div>
          <div class="row">ch <span class="field">0</span></div>
          <span class="btn">Write LEDs</span>
        </div>
        """,
    ),
]


def shell(main: str, sub: str | None) -> str:
    tabs = ["About", "ADC Registers", "Analysis", "Save", "MMB0"]
    tab_html = "".join(
        f'<span class="{"on" if t == main else ""}">{t}</span>' for t in tabs
    )
    badge = f'<span class="badge">doc render · mirrors live ads1299-gui</span>'
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>ADS1299EEG-FE — {main}{(' / '+sub) if sub else ''}</title>
<link rel="stylesheet" href="style.css"/>
</head><body>
<div class="window">
  <div class="titlebar"><div class="dots"><i class="r"></i><i class="y"></i><i class="g"></i></div>
    ADS1299EEG-FE — Python EVM (SLAU443B parity)</div>
  <div class="top">
    <div class="brand">ADS1299EEG-FE</div>
    <div class="sub">MMB0 / USBStyx</div>
    {badge}
    <div class="spacer"></div>
    <span class="btn">Show/Poll Lead-Off</span>
    <span class="btn">Read Registers</span>
    <span class="btn">Disconnect</span>
    <span class="btn">Connect</span>
  </div>
  <div class="progress"><span></span></div>
  <div class="tabs">{tab_html}</div>
  <div class="content">BODY_PLACEHOLDER</div>
  <div class="status">Disconnected — USB idle</div>
</div>
</body></html>
"""


def main() -> int:
    HTML.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    chrome = Path(CHROME)
    if not chrome.exists():
        print("Chrome not found", file=sys.stderr)
        return 1

    manifest = ["# GUI screenshot manifest", "", "| File | Description |", "|------|-------------|"]
    for stem, main_tab, sub, body in PAGES:
        html = shell(main_tab, sub).replace("BODY_PLACEHOLDER", body)
        path = HTML / f"{stem}.html"
        path.write_text(html, encoding="utf-8")
        out = SHOTS / f"{stem}.png"
        # Capture the .window at 1280x820 + margins → clip via window-size
        cmd = [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size=1328,900",
            f"--screenshot={out}",
            path.as_uri(),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"wrote {out.name} ({out.stat().st_size} bytes)")
        label = main_tab if not sub else f"{main_tab} → {sub}"
        manifest.append(f"| `{stem}.png` | {label} |")

    (SHOTS / "MANIFEST.md").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
