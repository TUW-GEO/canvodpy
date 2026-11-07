# Temporal aggregation averages SNR in dB

*Accepted 2026-11-07 (#192).*

The optional temporal aggregation of a run (canvod-ops) bins the epochs of
each receiver and takes the mean or the median per bin. SNR is stored in
dB-Hz, a logarithm of power, so the mean can be taken of the dB values or
of the linear power converted back to dB. The two differ: the mean of the
dB values is at most the dB of the mean power, and equal only when all
values in the bin are equal. The median is the same on both scales,
because the conversion keeps the order (up to the midpoint rule for an
even number of values).

**The mean is taken of the SNR in dB.** VOD is linear in the SNR
difference in dB:

```
VOD = -ln(T) · cos θ,   T = 10^(ΔSNR/10)
VOD = -(ln 10 / 10) · ΔSNR · cos θ
```

For a fixed θ and the same epochs at both receivers, the mean of each
receiver's SNR in dB therefore gives the mean of the per-epoch VOD. The
mean of the linear power gives `-ln(mean P_canopy / mean P_reference) ·
cos θ`, a ratio of means, which is neither the mean VOD nor the mean
transmissivity. Computing VOD per epoch and then averaging VOD is also
the published practice (Humphrey and Frankenberg 2023,
<https://bg.copernicus.org/articles/20/1789/2023/>).

## Considered options

- **The mean of the linear power.** Gives a ratio of means, not the mean
  VOD (see the decision).
- **Only the median.** Independent of the scale, but it drops the mean,
  which gives the mean VOD under the conditions below.

## Consequences

- The equivalence holds exactly only when θ is fixed within a bin and
  both receivers' bins average the same epochs. θ changes within a bin
  as a satellite moves; the effect is measured in #192 and documented in
  the canvod-ops overview. Aggregation runs per receiver, so a canopy bin
  and a reference bin can average different epochs; #192 tracks this,
  together with a count of the epochs per bin.
- Integer variables (flags) are not averaged: they take the first, last,
  or middle value of the bin (`integer_method`).
