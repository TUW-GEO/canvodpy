# SBF Field Decoding Reference

Every value stored in `obs_ds` and the `sbf_obs` metadata dataset is derived
from raw SBF integers through a well-defined transformation.  This page documents
each formula with the source field type, the arithmetic applied, and the firmware
page reference.

All page references are to the
**Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide** (abbreviated
**RefGuide-4.14.0**) unless stated otherwise.

---

## Epoch Timestamps

**Source:** `MeasEpoch` header — `WNc` (u2) + `TOW` (u4, milliseconds).
**Source block:** ReceiverTime (ΔLS), RefGuide-4.14.0 p.369.

GPS Time uses a fixed epoch and has no leap seconds; UTC is obtained by
subtracting the current GPS–UTC offset ΔLS:

$$
t_\text{UTC} = t_\text{GPS epoch} + \frac{WN_c \times 604800 \times 10^3 + TOW}{10^3} - \Delta_\text{LS}
$$

| Symbol | Meaning | Value |
|--------|---------|-------|
| $t_\text{GPS epoch}$ | GPS reference epoch | 1980-01-06 00:00:00 UTC |
| $WN_c$ | Continuous GPS week number | from `MeasEpoch.WNc` |
| $TOW$ | Time of Week | ms, from `MeasEpoch.TOW` |
| $\Delta_\text{LS}$ | GPS − UTC leap-second offset | 18 s (valid from 2017-01-01; updated from `ReceiverTime` when present) |

---

## Signal Number Decoding

**Source:** `MeasEpochChannelType1.Type` (u1) and `ObsInfo` (u1), p.262.

The 5 least-significant bits of `Type` carry a *signal index*:

$$
\text{SigIdxLo} = \text{Type} \;\&\; 0x1F
$$

If $\text{SigIdxLo} = 31$ the signal number is extended via `ObsInfo`:

$$
\text{sig_num} = \left(\frac{\text{ObsInfo} \gg 3}{} \;\&\; 0x1F\right) + 32
$$

Otherwise $\text{sig_num} = \text{SigIdxLo}$.  The mapping from signal number
to constellation / band / tracking code is defined in the signal type table
(RefGuide-4.14.0 §4.1.10, p.256).

---

## C/N₀ (SNR)

**Source:** `MeasEpochChannelType1.CN0` (u1), p.264.
**Dataset variable:** `SNR` (units: `dB-Hz`).

The raw byte encodes carrier-to-noise density in two different scales depending
on the signal type:

$$
C/N_0 = \begin{cases}
  \text{CN0}_\text{raw} \times 0.25 + 10 & \text{all signals except 1 and 2} \\
  \text{CN0}_\text{raw} \times 0.25       & \text{signals 1 (GPS L1P) and 2 (GPS L2P)}
\end{cases}
$$

Signals 1 and 2 are tracked *semi-codeless* and have a lower intrinsic $C/N_0$;
the firmware omits the +10 dB offset and enforces a minimum of 1 dB‑Hz.

**Do-Not-Use:** raw value 255 → stored as NaN.

### CN0HighRes correction (MeasExtra)

**Source:** `MeasExtra.MeasExtraChannelSub.Misc` bits 0–2 (u3), p.265.

When `MeasExtra` (Block 4000) is logged, the reader applies an additional
sub-quantisation correction that extends resolution from 0.25 dB to 1/32 dB:

$$
C/N_{0,\,\text{final}} = C/N_0 + \underbrace{({\rm Misc} \;\&\; 0x07)}_{\text{CN0HighRes}\;\in\{0,\ldots,7\}} \times 0.03125
$$

If `MeasExtra` is absent the correction is zero (NaN guard prevents modification).

| Resolution | Source |
|---|---|
| 0.25 dB-Hz | `MeasEpoch.CN0` alone |
| 0.03125 dB-Hz (1/32 dB-Hz) | after CN0HighRes correction |

---

## Pseudorange

**Source:** `MeasEpochChannelType1.Misc` bits 0–3 (`CodeMSB`, u4-equivalent),
`CodeLSB` (u4), p.262.

$$
PR = \bigl(\text{CodeMSB} \times 2^{32} + \text{CodeLSB}\bigr) \times 10^{-3} \quad [\text{m}]
$$

where $\text{CodeMSB} = \text{Misc} \;\&\; 0x0F$.

**Do-Not-Use:** CodeMSB = 0 **and** CodeLSB = 0 → NaN.

### Type2 (slave signal) pseudorange

**Source:** `MeasEpochChannelType2.OffsetsMSB` bits 0–2 (`CodeOffsetMSB`,
3-bit two's-complement, range −4 to +3), `CodeOffsetLSB` (u2), p.264.

$$
PR_2 = PR_1 + \bigl(\text{CodeOffsetMSB} \times 65536 + \text{CodeOffsetLSB}\bigr) \times 10^{-3} \quad [\text{m}]
$$

**Do-Not-Use:** CodeOffsetMSB = −4 **and** CodeOffsetLSB = 0 → NaN.

---

## Doppler Shift

**Source:** `MeasEpochChannelType1.Doppler` (i4), p.263.

$$
D = \text{Doppler}_\text{raw} \times 10^{-4} \quad [\text{Hz}]
$$

Positive Doppler indicates a closing range (approaching satellite).

**Do-Not-Use:** raw = −2 147 483 648 ($= -2^{31}$, i4 minimum) → NaN.

### Type2 (slave signal) Doppler

**Source:** `MeasEpochChannelType2.OffsetsMSB` bits 3–7 (`DopplerOffsetMSB`,
5-bit two's-complement, range −16 to +15), `DopplerOffsetLSB` (u2), p.264.

The Type2 Doppler includes a frequency-ratio correction to account for the
different carrier frequency of the slave signal:

$$
D_2 = D_1 \times \frac{f_2}{f_1}
  + \bigl(\text{DopplerOffsetMSB} \times 65536 + \text{DopplerOffsetLSB}\bigr) \times 10^{-4} \quad [\text{Hz}]
$$

where $f_1, f_2$ are the carrier frequencies of the Type1 (master) and Type2
(slave) signals respectively.

**Do-Not-Use:** DopplerOffsetMSB = −16 **and** DopplerOffsetLSB = 0 → NaN.

---

## Carrier Phase

**Source:** `MeasEpochChannelType1.CarrierMSB` (i1), `CarrierLSB` (u2), p.263–264.

The carrier phase is encoded as a fractional offset relative to the pseudorange,
expressed in cycles.  Let $\lambda = c / f$ be the carrier wavelength:

$$
L = \frac{PR}{\lambda} + \bigl(\text{CarrierMSB} \times 65536 + \text{CarrierLSB}\bigr) \times 10^{-3} \quad [\text{cycles}]
$$

$$
\lambda = \frac{c}{f} \quad \text{where } c = 299\,792\,458 \;\text{m/s}
$$

**Do-Not-Use:** CarrierMSB = −128 **and** CarrierLSB = 0 → NaN.

### Type2 carrier phase

$$
L_2 = \frac{PR_2}{\lambda_2} + \bigl(\text{CarrierMSB}_2 \times 65536 + \text{CarrierLSB}_2\bigr) \times 10^{-3} \quad [\text{cycles}]
$$

Uses $PR_2$ (Type2 pseudorange, above) and the slave signal wavelength $\lambda_2$.

---

## GLONASS FDMA Carrier Frequencies

**Source:** `ChannelStatus.ChannelSatInfo.FreqNr`, RefGuide-4.14.0 §4.1.10 p.256 and
ChannelStatus Block 4013 p.393.

GLONASS uses Frequency Division Multiple Access (FDMA).  The centre frequency
depends on the frequency slot $K = \text{FreqNr} - 8$.

!!! note "FreqNr range differs by firmware version"
    RefGuide-4.14.0 allows slot range −7 to +13 (FreqNr 1–21).
    RefGuide-4.15.1 restricts this to −7 to +6 (FreqNr 1–14),
    matching the current GLONASS ICD allocation.

$$
f_{L1}(K) = 1602 + K \times \frac{9}{16} \quad [\text{MHz}]
$$

$$
f_{L2}(K) = 1246 + K \times \frac{7}{16} \quad [\text{MHz}]
$$

These frequencies are used as $f$ in the carrier phase wavelength formula and as
$f_1, f_2$ in the Type2 Doppler formula.

GLONASS L3 CDMA (signal 12) has a fixed frequency of 1202.025 MHz and does not
use this formula.

---

## Satellite Geometry (SatVisibility → θ, φ)

**Source:** `SatVisibility.SatInfo.Elevation` (i2, scale 0.01 °/LSB),
`Azimuth` (u2, scale 0.01 °/LSB), RefGuide-4.14.0 p.400.

### Polar angle θ

The SBF block stores elevation above the horizon.  `canvod-readers` converts to
the *polar angle* (co-elevation) used in the Tau-Omega VOD formula:

$$
\theta\,[\text{rad}] = \text{deg2rad}\!\left(90 - \text{Elevation}_\text{raw} \times 0.01\right)
$$

| θ | Geometry |
|---|---|
| $\theta = 0$ | satellite at zenith (directly overhead) |
| $\theta = \pi/2$ | satellite at the horizon |

### Azimuth φ

$$
\phi\,[\text{rad}] = \text{deg2rad}\!\left(\text{Azimuth}_\text{raw} \times 0.01\right)
$$

The stored azimuth is the geographic (compass) convention: 0 = North, π/2 = East,
measured clockwise.  Both θ and φ are stored in **radians** as `broadcast_theta`
and `broadcast_phi` in the `sbf_obs` metadata dataset.

---

## MeasExtra Signal-Quality Fields

All fields below are sourced from `MeasExtra` Block 4000,
`MeasExtraChannelSub` sub-block, p.265.

### Multipath correction (pseudorange)

$$
\Delta PR_\text{MP} = \text{MPCorrection}_\text{raw} \times 10^{-3} \quad [\text{m}]
$$

Raw field: i2.  Add to the stored pseudorange to recover the
unmitigated measurement before firmware multipath filtering.

### Smoothing correction (pseudorange)

$$
\Delta PR_\text{smooth} = \text{SmoothingCorr}_\text{raw} \times 10^{-3} \quad [\text{m}]
$$

Raw field: i2.  Add to the stored pseudorange to recover the raw
unsmoothed measurement before Hatch-filter carrier smoothing.

### Code tracking variance

$$
\sigma_\text{code}^2 = \text{CodeVar}_\text{raw} \times 10^{-4} \quad [\text{m}^2]
$$

Raw field: u2.  Estimated noise variance of the code-phase measurement.
Maximum representable value is 6.5534 m² (raw = 65534). **Do-Not-Use:** 65535 → NaN.

### Carrier tracking variance

$$
\sigma_\text{carrier}^2 = \text{CarrierVar}_\text{raw} \quad [\text{mcycles}^2]
$$

Raw field: u2, direct copy (scale = 1 mcycle²/LSB).  Maximum 65534 mcycles².
**Do-Not-Use:** 65535 → NaN.

The corresponding Doppler variance is:

$$
\sigma_D^2 = \sigma_\text{carrier}^2 \times D_\text{VarFactor} \quad [\text{Hz}^2]
$$

where `DopplerVarFactor` (MeasExtra block header, p.264) is a per-epoch scale
factor that converts mcycles² to Hz².

### Lock time

$$
T_\text{lock} = \text{LockTime}_\text{raw} \quad [\text{s}]
$$

Raw field: u2.  Duration of uninterrupted carrier phase tracking.  Reset to 0 on
reacquisition.  Clipped to 65534 s.  **Do-Not-Use:** 65535 → NaN.

### Cumulative loss-of-continuity counter

$$
N_\text{slip} = \text{CumLossCont}_\text{raw} \quad \text{(modulo 256)}
$$

Raw field: u1, direct copy.  Increments at every reacquisition or cycle slip.  A
change $\Delta N_\text{slip} \neq 0$ between consecutive epochs is a direct
indicator of a carrier-phase discontinuity (cycle slip).

### Carrier multipath correction

$$
\Delta L_\text{MP} = \frac{\text{CarMPCorr}_\text{raw}}{512} \quad [\text{cycles}]
$$

Raw field: i1, scale $1/512$ cycles/LSB ($\approx 1.953 \times 10^{-3}$ cycles/LSB).
Add to the stored carrier phase to recover the unmitigated phase.

---

## Auxiliary Scalar Fields

Fields stored with a simple scale or offset:

| Variable | Source block | Raw field | Formula | Unit |
|---|---|---|---|---|
| `pdop`, `hdop`, `vdop` | DOP (Block 4001), fallback PVTGeodetic | u2 | raw × 0.01 | 1 |
| `h_accuracy_m` | PVTGeodetic (Block 4007) `HAccuracy` | u2 | raw × 0.01; DNU 65535 | m |
| `v_accuracy_m` | PVTGeodetic (Block 4007) `VAccuracy` | u2 | raw × 0.01; DNU 65535 | m |
| `mean_corr_age_s` | PVTGeodetic (Block 4007) `MeanCorrAge` | u2 | raw × 0.01 | s |
| `temperature_c` | ReceiverStatus (Block 4014) `Temperature` | u1 | raw − 100; DNU 0 | °C |

Page references: DOP block p.349, PVTGeodetic pp.337–339, ReceiverStatus pp.396–399.

---

## Summary: Non-trivial Transformations

| Observable | Non-trivial step |
|---|---|
| **SNR** | Signal-dependent formula (±10 dB offset); two-pass correction from MeasExtra |
| **Pseudorange** | 40-bit reconstruction from two fields (CodeMSB × 2³² + CodeLSB); Type2 adds delta |
| **Carrier phase** | Mixed-unit formula: pseudorange converted to cycles via λ = c/f, then phase delta added |
| **Type2 Doppler** | Frequency-ratio scale factor applied before adding delta |
| **θ (polar angle)** | Elevation → co-elevation (90° −  elevation), then degrees → radians |
| **φ (azimuth)** | Scale 0.01°/LSB, degrees → radians |
| **GLONASS frequencies** | Slot-dependent FDMA formula required for λ and Type2 Doppler |
| **Epoch** | GPS week + TOW (ms) → UTC datetime via leap-second subtraction |
| **CN0HighRes** | Bit-field extraction (bits 0–2) then scale 1/32 dB-Hz/LSB |
| **CarMPCorr** | Integer division by 512 to convert i1 to fractional cycles |

---

## References

- Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide
- Septentrio AsteRx SB3 ProBase Firmware v4.15.1 Reference Guide
- IS-GPS-200 Rev. N §20.3.3.5.2.4 — GPS time and leap seconds
- RINEX 3.04 signal nomenclature — used verbatim for SID code strings

---

!!! example "Try it"
    [06 · SBF Reading](../../notebooks/_build/06_sbf_reading.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/06_sbf_reading.py)
