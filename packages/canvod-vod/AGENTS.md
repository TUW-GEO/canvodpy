# canvod-vod

VOD calculators: canopy and reference observations in, VOD out.

## Where things live

| Path | What |
|---|---|
| `src/canvod/vod/calculator.py` | `VODCalculator` (ABC and pydantic model), `TauOmegaZerothOrder` |

Background: `docs/packages/vod/overview.md`.

## Invariants

- Zeroth-order tau-omega: `delta_snr = SNR_canopy - SNR_reference` (dB),
  `T = 10 ** (delta_snr / 10)`, `VOD = -ln(T) · cos(θ)`, θ of the canopy
  receiver. This is a scientific guardrail.
- Output passes `validate_vod_dataset` (canvod-readers); the VOD store
  refuses anything else.
- Calculators in other packages reach `canvodpy run` as plugins (entry
  point group `canvodpy.vod_calculators`, `docs/guides/plugins.md`). Like
  `TauOmegaZerothOrder`, they keep the canopy's `cell_id_*` variables.
- In a run, `VodComputer` (canvodpy) is the only caller: it picks the
  canopy/reference pairs and days and writes the VOD store. Don't build a
  second VOD path on `from_icechunkstore` or `from_datasets`.

## Tests

```bash
just test-package canvod-vod
```
