# RINEX v2.11 parsing

`Rnxv2Obs` reads [RINEX 2.11](https://files.igs.org/pub/data/format/rinex211.txt){:target="_blank"} observation files into the same `(epoch × sid)` Dataset that `Rnxv3Obs` produces. The format specification ships next to the reader as `canvod/readers/rinex/rinex211.txt`; every rule on this page cites it.

```python
from pathlib import Path
from canvod.readers import Rnxv2Obs

ds = Rnxv2Obs(fpath=Path("p0481660.08o")).to_ds(keep_data_vars=["SNR", "Phase"])
```

---

## One data structure: RINEX 3 signal IDs

canvodpy has one signal axis for every input format: `SV|BAND|CODE`, with bands and tracking codes in [RINEX 3 nomenclature](rinex-format.md#signal-id-mapping). A RINEX 3 observation code names the signal completely: `L2W` is the phase of the L2 P-code tracked by Z-tracking or a similar technique under antispoofing (RINEX 3.04 Table 4), `L2L` the phase of the L2C pilot channel. Two signals with different codes are different measurements, and canvodpy keeps them apart until an analysis explicitly aggregates them.

RINEX 2 cannot express that. Its observation codes are one letter for the observable and one digit for the frequency (`L2`, `P2`, `C1`, `S1`). RINEX 2.11 Table A1 defines only two pseudorange families:

| RINEX 2 code | Defined as (Table A1) |
|---|---|
| `C1` | GPS C/A · GLONASS C/A · Galileo "All" |
| `C2` | GPS C/A or L2C (Table A1 does not distinguish them) |
| `P1`, `P2` | GPS / GLONASS P code |
| `Lx`, `Dx`, `Sx` | carrier phase, Doppler, signal strength on frequency *x*, no code |

and section 10.1.1 states that the two-character code cannot express the underlying code (P, Y, M in GPS) or the channel (for example I/Q in L5, the GPS L2C channels). Table A1 adds that observations collected under antispoofing are stored as "L2" or "P2," so the tracking technique is not recorded either. Phase, Doppler, and signal strength carry no code information at all.

Mapping RINEX 3 down to RINEX 2 would throw that information away for every modern file. canvodpy therefore lifts RINEX 2 up into the RINEX 3 structure, and fills in only what RINEX 2 itself defines.

---

## Lowercase tracking-code markers

Where RINEX 2 leaves the code unresolved, the reader writes a **lowercase** marker in the code position:

| Marker | Meaning | Candidate RINEX 3 codes | From |
|---|---|---|---|
| `p` | P-code family, technique not recorded | `P`, `W`, `Y`; `D` on L2 only (RINEX 3.04 Table 4) | GPS `P1`, `P2` |
| `l` | civil code on L2 (C/A or L2C), not recorded which | `C`, `S`, `L`, `X` | GPS `C2` |
| `u` | carrier band only, no code information | any | phase, Doppler, signal strength; Galileo and L5 pseudoranges |

RINEX 3 and 4 attributes are uppercase only, so a marker can never collide with a real code. A plausible-looking uppercase guess would: `X` is a real signal (the combined L1C D+P or L2C M+L channel), and `W` asserts a tracking technique the file does not record.

Where RINEX 2 *does* identify the signal, the reader writes the real RINEX 3 code:

- **GPS `C1`** is the C/A code $\rightarrow$ `C`.
- **GLONASS `C1`/`C2`** are C/A $\rightarrow$ `C`; **`P1`/`P2`** are the P code, for which RINEX 3.04 Table 5 defines a single attribute $\rightarrow$ `P`.
- A **band with a single RINEX 3 signal** resolves to that signal for every observable: SBAS L1 carries only C/A, so SBAS `C1`, `L1`, `S1` all become `L1|C`.

| System | RINEX 2 code | Signal ID |
|---|---|---|
| GPS | `C1` | `G05\|L1\|C` |
| GPS | `P1` | `G05\|L1\|p` |
| GPS | `P2` | `G05\|L2\|p` |
| GPS | `C2` | `G05\|L2\|l` |
| GPS | `L1`, `D1`, `S1` | `G05\|L1\|u` |
| GPS | `L2`, `D2`, `S2` | `G05\|L2\|u` |
| GLONASS | `C1` / `P2` | `R07\|G1\|C` / `R07\|G2\|P` |
| GLONASS | `L1`, `S1` | `R07\|G1\|u` |
| Galileo | `C1`, `L1`, `S1` | `E11\|E1\|u` |
| SBAS | `C1`, `L1`, `S1` | `S20\|L1\|C` |
| SBAS | `C5`, `L5`, `S5` | `S20\|L5\|u` |

Two consequences follow directly from the specification:

- **Phase and signal strength of a RINEX 2 file share one SID per band** (`L1|u`), and the pseudoranges get their own (`L1|C`, `L1|p`). Table A1 describes signal strength as belonging "to the respective phase observations"; neither is tied to a code.
- **Selecting a RINEX 3 code picks up RINEX 2 data only where RINEX 2 defines that code** (for example GPS `C1` in `L1|C`). `ds.sel(sid=ds.code == "W")` returns nothing from a RINEX 2 file, because RINEX 2 never said the signal was `W`. To use the remaining RINEX 2 data, select the markers explicitly and decide how to treat them.

Every RINEX 2 dataset documents the markers in its `"Tracking Code Markers"` attribute and records the source version in `"RINEX Version"`.

!!! note "Global SID padding"
    The markers are registered in the constellation `BAND_CODES`, so
    `pad_to_global_sid()` keeps them. RINEX 2 and RINEX 3 data of the same
    station can share one store: their SIDs are disjoint wherever RINEX 2
    could not resolve the code, and identical where it could (`G05|L1|C`).

---

## Default SID preset

The `default` SID preset is defined in RINEX 3 codes, which RINEX 2 signal strength never carries. Band-only SIDs are populated only from RINEX 2 files, so the preset does not include them; otherwise every RINEX 3 or SBF dataset would carry them as empty SIDs. To process RINEX 2 files, select them explicitly (`sids: mode: custom`). The commented-out block at the end of `presets/default.yaml` lists the band-only SIDs of the satellites of the preset that follow its exclusion rule (no codeless or semi-codeless tracking):

| Band | RINEX 3 candidates for `u` | Listed |
|---|---|---|
| GLONASS G1 | `C`, `P`; RINEX 3.04 defines codeless/semi-codeless attributes for GPS only (Sect. 5.1) | `Rnn\|G1\|u` |
| Galileo E1 | `A`, `B`, `C`, `X`, `Z`; likewise no codeless/semi-codeless attribute | `Enn\|E1\|u` |
| GPS L1 | C/A, L1C, P(Y) codeless (`N`) or Z-tracking (`W`) | `Gnn\|L1\|u`, **assuming** S1 does not come from codeless or Z-tracking of P(Y) |
| GPS L2 | L2C, C/A, or P(Y) | excluded: without L2C, L2 carries P(Y) or, by ground command, C/A (IS-GPS-200N Sect. 3.2.3); civil receivers track P(Y) only by codeless or semi-codeless processing (Betz & Cerruti 2020, doi:10.1002/navi.347), and RINEX 2 cannot tell these modes from L2C |

GLONASS G2 and Galileo E5a/E5b band-only SIDs are not listed.

---

## Satellites

RINEX 2 satellite numbers `snn` follow the same convention as RINEX 3: for SBAS, $nn = \text{PRN} - 100$ (PRN 120 $\rightarrow$ `S20`). SBAS satellites `S01`–`S99` are recognized.

---

## Loss of lock and signal strength indicators

The `LLI` variable has the [RINEX 3.04 meaning](rinex-format.md#loss-of-lock-and-signal-strength-indicators) for every input format. The RINEX 2.11 bits (Table A2) differ, so the reader translates them:

| Bit | RINEX 2.11 (Table A2) | Written as (RINEX 3.04 Table A3) |
|---|---|---|
| 0 | lost lock, cycle slip possible | bit 0, unchanged |
| 1 | wavelength factor opposite to the one in force | bit 1 (half-cycle ambiguity) if the phase's resulting factor is 2 |
| 2 | observation under antispoofing | dropped: RINEX 3.04 sect. 7 declares the antispoofing flag obsolete |

The `WAVELENGTH FACT L1/2` header record gives the factor for GPS L1 and L2 phase: 1 = full-cycle, 2 = half-cycle ambiguities (squaring receivers). The factor in force is the header default or a satellite-specific record, including records inserted with epoch flag 4 later in the file. Bit 1 switches it for the current epoch only. Every phase with factor 2 gets RINEX 3 bit 1, even without an LLI digit.

Phase, Doppler, and signal strength of one band land in one SID, and some converters write flags on every observable. Following RINEX 3.04 Table A3 notes 1–3:

- **LLI** is taken only from the phase observation. Flags on code, Doppler, or signal strength are ignored.
- **SSI** is taken from the phase; for a SID without phase, from the pseudorange. RINEX 2.11 does not assign the SSI to an observable.

## Signal strength unit

RINEX 2.11 Table A1 defines `S` as "raw signal strengths or SNR values as given by the receiver" and declares no unit. `SNR` is labeled dB, and its `description` attribute states the assumption.

---

## Header

`obs_codes_per_system` lists the observation codes in RINEX 3 notation per system, with the resolved code or marker in the attribute position, for a mixed GPS/GLONASS file with `L1 L2 C1 P1 P2 S1 S2`:

```python
{
    "G": ["L1u", "L2u", "C1C", "C1p", "C2p", "S1u", "S2u"],
    "R": ["L1u", "L2u", "C1C", "C1P", "C2P", "S1u", "S2u"],
}
```
