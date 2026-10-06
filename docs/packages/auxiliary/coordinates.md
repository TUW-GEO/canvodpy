# Coordinate Systems

canvod-auxiliary works with three [coordinate systems](https://gssc.esa.int/navipedia/index.php/Reference_Frames_in_GNSS){:target="_blank"}. Knowing which one is used where prevents sign errors and unit confusion in downstream VOD calculations.

<div class="grid cards" markdown>

-   :fontawesome-solid-earth-americas: &nbsp; **ECEF**

    ---

    Earth-Centered, Earth-Fixed Cartesian **(X, Y, Z)** in metres.
    Used in SP3 ephemerides and the internal satellite position pipeline.

-   :fontawesome-solid-location-dot: &nbsp; **Geodetic (WGS84)**

    ---

    Latitude, longitude (degrees), altitude above ellipsoid (metres).
    Stored in RINEX headers as the approximate receiver position.

-   :fontawesome-solid-compass: &nbsp; **Spherical (receiver-relative)**

    ---

    Slant range **r**, polar angle **θ**, geographic azimuth **φ**.
    This is the output added to the obs Dataset for VOD geometry.

</div>

---

## ECEF Coordinates

Satellite positions from SP3 files are ECEF Cartesian coordinates in metres, one position per satellite and epoch.

```python
from canvod.auxiliary import ECEFPosition

# From raw values
ecef = ECEFPosition(x=4_075_539.8, y=931_735.3, z=4_801_629.6)

# From RINEX Dataset metadata (reads APPROX POSITION header)
ecef = ECEFPosition.from_ds_metadata(rinex_ds)

# Convert to geodetic
lat, lon, alt = ecef.to_geodetic()
```

---

## Geodetic Coordinates

WGS84 geodetic coordinates for the **receiver** position — read from the `APPROX POSITION XYZ` RINEX header field.

```python
from canvod.auxiliary import GeodeticPosition

geo = GeodeticPosition(lat=48.2, lon=16.4, alt=200.0)

# Convert to ECEF for vector calculations
ecef = geo.to_ecef()  # ECEFPosition
```

---

## Spherical Coordinates (receiver-relative)

The key output of the auxiliary pipeline — added to the obs Dataset as `theta` and `phi` coordinates for each `(epoch, sid)` cell.

| Variable | Symbol | Range | Convention |
|----------|--------|-------|------------|
| Slant range | r | ≥ 0 m | Distance from receiver antenna to satellite |
| Polar angle | θ | 0 … π/2 | 0 = overhead (zenith), π/2 = horizon |
| Geographic azimuth | φ | 0 … 2π | 0 = North, π/2 = East, clockwise |

All three are NaN while the satellite is below the receiver's horizon.

!!! note "Polar angle vs elevation"
    VOD literature often uses **elevation** angle `e = π/2 − θ`.
    canvod-auxiliary stores **polar angle** θ internally.
    The `cos(θ)` factor in the tau-omega formula uses θ directly:
    `VOD = −ln(T) · cos(θ)`.

---

## Computing Spherical Coordinates

```python
from canvod.auxiliary import compute_spherical_coordinates

r, theta, phi = compute_spherical_coordinates(
    # satellite ECEF positions, arrays of any shape
    sat_x,
    sat_y,
    sat_z,
    receiver_position,  # ECEFPosition
)
```

The function:

1. Subtracts the receiver ECEF position from each satellite ECEF position.
2. Rotates the difference vector into the local ENU (East-North-Up) frame.
3. Converts ENU to spherical `(r, θ, φ)` and sets all three to NaN below the horizon.

---

## Adding Coordinates to Datasets

In a run the interpolated satellite positions are first selected for each signal, so `(r, θ, φ)` come out on `(epoch, sid)` and are attached to the observation dataset:

```python
from canvod.auxiliary import add_spherical_coords_to_dataset

augmented_ds = add_spherical_coords_to_dataset(rinex_ds, r, theta, phi)

# New data variables on (epoch, sid):
# augmented_ds["theta"]   → polar angle [rad]
# augmented_ds["phi"]     → geographic azimuth [rad]
# augmented_ds["r"]       → slant range [m]
```

A run keeps `r` only when `processing.params.store_radial_distance` is
`true` (default `false`).

---

!!! example "Try it"
    [05 — Ephemeris & Coordinates](../../notebooks/_build/05_ephemeris_coordinates.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/05_ephemeris_coordinates.py)
