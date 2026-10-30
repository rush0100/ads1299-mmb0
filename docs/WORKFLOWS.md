# Workflows

Host-side control plane: **USB bootloader → DSP firmware → USBStyx (9P) → ADS1299 registers / data**. The PC never drives SPI directly.

## System architecture

```mermaid
flowchart LR
  subgraph Host["Host (Python)"]
    GUI["ads1299-gui / CLI"]
    LIB["ads1299_mmb0"]
    GUI --> LIB
  end
  subgraph USB["USB"]
    BOOT["Bootloader\n0451:9001"]
    STYX["USBStyx bulk\n0451:5718"]
  end
  subgraph Board["MMB0 + ADS1299EEG-FE"]
    DSP["C5509 DSP FW"]
    FS["Styx FS\n/version /mmb0/*\n/ads1299evm/*"]
    SPI["SPI"]
    ADC["ADS1299"]
    DSP --> FS
    DSP --> SPI --> ADC
  end
  LIB -->|load .bin| BOOT
  BOOT -->|re-enumerate| STYX
  LIB -->|9P Tattach/Tread/Twrite| STYX
  STYX --> DSP
```

## Connect / firmware load

```mermaid
sequenceDiagram
  participant U as User / GUI
  participant S as DeviceSession
  participant B as Bootloader 0451:9001
  participant D as DSP + Styx 0451:5718
  U->>S: Connect
  S->>B: Detect USB (optional)
  alt needs firmware
    S->>B: Upload ads1299evm-pdk.bin
    B-->>D: Re-enumerate
  end
  S->>D: Styx attach
  S->>D: Read /version, registers, /mmb0/*
  S-->>U: Connected + register refresh
```

**CLI:** `ads1299-load --wait -f "$ADS1299_FIRMWARE"` then `ads1299-gui` or `ads1299-shell --no-load`.

If bulk USB wedges after a bad acquire: power-cycle the MMB0 wall wart, wait for `0451:9001`, load again.

## Register write

```mermaid
flowchart TD
  A[Edit bit fields or hex] --> B[Apply / Set]
  B --> C["session.write_register(styx, value)"]
  C --> D["9P write /ads1299evm/conf/<name>"]
  D --> E[DSP SPI to ADS1299]
  E --> F[Update HexSpin + Register Map row]
```

Global CONFIG packing helpers live in `presets.pack_config*`; channel packing in `registers.chset`.

## Block acquire (primary path)

Stock firmware is **buffer-then-USB** (~1 MB ≈ ~28k frames).

```mermaid
sequenceDiagram
  participant U as Analysis tab
  participant S as DeviceSession
  participant D as /ads1299evm/*
  U->>U: Set frames / Vref / Gain
  U->>S: Acquire
  S->>D: Configure blocksize = frames × 9 words
  S->>D: Start acquire (do not poll /acquire while filling)
  S->>D: Read /ads1299evm/data
  S->>S: Decode BE int32 → volts
  S-->>U: Scope / FFT / Histogram / Analysis redraw
```

**Important (FW 0.0.27):** `blocksize` is int32 **word** count and must be `9 * n_frames` (status + 8 channels). Word counts not divisible by 9 hang the DSP.

## Segmented continuous capture

```mermaid
flowchart LR
  A[Start] --> B[Capture chunk_frames]
  B --> C[Append / rolling scope]
  C --> D{Stop or duration?}
  D -->|no| E[Gap on USB expected]
  E --> B
  D -->|yes| F[Final plots + status]
```

Not zero-gap streaming. True continuous needs custom DSP firmware (out of scope).

## Presets (SLAU443B-style)

```mermaid
flowchart TD
  P[Preset button] --> W[Write preset register map]
  W --> R[Read Registers]
  R --> A[Auto Acquire]
  A --> V[View Scope/FFT]
```

| Preset | Intent |
|--------|--------|
| Input short noise | All CH MUX=short, refbuf on, 250 SPS |
| Internal test signal | CONFIG2 INT_CAL + MUX=test |
| Impedance @ 31.2 Hz | AC lead-off FLEAD=31.2 Hz (needs JP25/J6) |
| Impedance @ fDR/4 | AC lead-off at fDR/4 (250 SPS → 62.5 Hz) |

## Lead-off poll

```mermaid
flowchart LR
  O[Open dialog] --> T[Every 500 ms]
  T --> R[Read loffstatp / loffstatn]
  R --> P[Paint P1–P8 / N1–N8]
  P -->|green| C[Connected bit]
  P -->|red| X[Open / fail]
```

## Save bundle

```mermaid
flowchart TD
  A[Last capture in session] --> B[Choose DataDir + notes]
  B --> C[Channel checkboxes]
  C --> D[CSV + NPY + meta.json]
  C --> E[CSV only dialog]
```

## CLI equivalents

```mermaid
flowchart TB
  subgraph GUI
    G1[Connect]
    G2[Acquire]
    G3[Save]
  end
  subgraph CLI
    C1["ads1299-load"]
    C2["ads1299-capture -n N"]
    C3["ads1299-shell"]
  end
  G1 -.-> C1
  G2 -.-> C2
  G3 -.-> C2
```

```bash
export ADS1299_FIRMWARE=/path/to/ads1299evm-pdk.bin
ads1299-load --wait -f "$ADS1299_FIRMWARE"
ads1299-capture -n 64 -o out.bin --npy out.npy
ads1299-gui
```

## Library acquire sketch

```python
from ads1299_mmb0 import ADS1299
from ads1299_mmb0.stream import acquire_continuous

with ADS1299.open() as dev:
    print(dev.read_path("/version"))
    volts = dev.acquire(n_samples=64)  # (64, 8) float volts
    long = acquire_continuous(dev, total_frames=8192, chunk_frames=4096)
```
