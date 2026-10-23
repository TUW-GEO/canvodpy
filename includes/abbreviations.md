<!-- Glossary: hover any abbreviation to see its definition -->

<!-- GNSS fundamentals — see Navipedia (navipedia.net) for detailed articles -->
*[GNSS]: Global Navigation Satellite System — umbrella term for GPS, Galileo, GLONASS, BeiDou, etc. (Navipedia: GNSS)
*[GPS]: Global Positioning System — US satellite navigation constellation, 31 SVs in 6 orbital planes (Navipedia: GPS)
*[GLONASS]: GLObal NAvigation Satellite System — Russian constellation using FDMA and CDMA signals (Navipedia: GLONASS)
*[BeiDou]: BeiDou Navigation Satellite System — Chinese constellation with regional and global services (Navipedia: BeiDou)
*[Galileo]: European Global Navigation Satellite System — 30 SVs, dual-frequency civilian design (Navipedia: Galileo)
*[IRNSS]: Indian Regional Navigation Satellite System (also known as NavIC) — 7-satellite regional system (Navipedia: IRNSS)
*[NavIC]: Navigation with Indian Constellation (IRNSS) — regional GNSS covering India and surroundings
*[QZSS]: Quasi-Zenith Satellite System — Japanese regional augmentation optimised for urban canyons (Navipedia: QZSS)
*[SBAS]: Satellite-Based Augmentation System — geostationary broadcasts providing integrity and corrections (Navipedia: SBAS)
*[FDMA]: Frequency Division Multiple Access — GLONASS signal multiplexing: each SV on a different frequency channel (Navipedia: GLONASS Signal Plan)
*[CDMA]: Code Division Multiple Access — signal multiplexing used by GPS, Galileo, BeiDou: all SVs on same frequency, distinguished by PRN code (Navipedia: GPS Signal Plan)

<!-- Satellite identifiers -->
*[PRN]: Pseudo-Random Noise — unique code identifying a satellite signal slot (e.g. G01, E02). PRN ≠ SVN; PRNs can be reassigned. (Navipedia: GNSS signal)
*[SVN]: Space Vehicle Number — permanent hardware identifier assigned at launch; does not change when PRN is reassigned
*[SID]: Signal Identifier — canVODpy format: SV|Band|Code (e.g. G01|L1|C). Uniquely identifies one observable per epoch.
*[SV]: Space Vehicle — a single GNSS satellite, identified by system prefix + PRN number

<!-- Observation data -->
*[SNR]: Signal-to-Noise Ratio — carrier power relative to noise floor, in dB-Hz. Key observable for GNSS transmissometry. (Navipedia: GNSS Measurements)
*[RINEX]: Receiver Independent Exchange Format — standard ASCII format for GNSS observations, defined by IGS (Navipedia: RINEX)
*[SBF]: Septentrio Binary Format — proprietary binary telemetry from Septentrio receivers; embeds satellite geometry
*[SINEX]: Solution INdependent EXchange format — IGS format for station coordinates, satellite metadata, and troposphere products

<!-- VOD and transmissometry -->
*[VOD]: Vegetation Optical Depth — dimensionless measure of microwave attenuation through vegetation canopy (τ = −ln(T)·cos θ)
*[GNSS-T]: GNSS Transmissometry — method using differential SNR between canopy and reference receivers to estimate vegetation properties
*[SCS]: Signal Comparison Strategy — comparing canopy vs reference receiver SNR to isolate vegetation attenuation

<!-- Ephemerides and orbits -->
*[SP3]: Standard Product 3 — precise satellite orbit (position ± ~2 cm) file format, produced by IGS analysis centres (Navipedia: SP3)
*[CLK]: Clock — precise satellite and station clock correction file (30 s intervals), companion to SP3 orbits
*[IGS]: International GNSS Service — global network of 500+ stations providing orbits, clocks, and reference frame products (Navipedia: IGS)
*[PVT]: Position, Velocity, Time — the receiver navigation solution computed from pseudoranges (Navipedia: GNSS Basic Observables)
*[DOP]: Dilution of Precision — scalar measure of how satellite geometry amplifies ranging errors (Navipedia: Dilution of Precision)
*[ECEF]: Earth-Centered Earth-Fixed — Cartesian (X,Y,Z) coordinate frame co-rotating with Earth (Navipedia: Reference Frames in GNSS)

<!-- Data standards -->
*[ACDD]: Attribute Convention for Dataset Discovery — NetCDF/CF metadata convention for self-describing datasets
*[STAC]: SpatioTemporal Asset Catalog — open specification for geospatial metadata and search
*[DataCite]: DataCite Metadata Schema — required metadata for DOI registration of research datasets
*[FAIR]: Findable, Accessible, Interoperable, Reusable — guiding principles for scientific data stewardship (Wilkinson et al. 2016)
*[SPDX]: Software Package Data Exchange — standardised license identifier system (e.g. MIT, Apache-2.0)

<!-- Infrastructure -->
*[Icechunk]: Version-controlled cloud-native tensor storage engine — git-like snapshots over Zarr v3 chunks
*[Zarr]: Chunked, compressed N-dimensional array storage format — cloud-native alternative to HDF5/NetCDF
*[xarray]: Labelled multi-dimensional arrays for Python — extends NumPy with named dims, coords, and attrs
*[Polars]: Fast DataFrame library written in Rust — used for metadata catalogs and inventory
*[loky]: Reusable Process Pool Executor - based on Python's native concurrent.futures
*[pydantic]: The fastest and most widely used data validation library for Python - written in Rust
*[DAG]: Directed Acyclic Graph — task dependency structure used by workflow schedulers (Airflow, Prefect)
*[CI]: Continuous Integration — automated build and test on every commit
*[CDDIS]: Crustal Dynamics Data Information System — NASA archive for GNSS orbits, clocks, and observation data
*[FTP]: File Transfer Protocol
*[ROR]: Research Organization Registry — persistent identifier for research institutions
*[ORCID]: Open Researcher and Contributor ID — persistent digital identifier for researchers
*[DOI]: Digital Object Identifier — persistent identifier for publications, datasets, and software

<!-- Coordinate systems -->
*[WGS84]: World Geodetic System 1984 — reference ellipsoid and datum used by GPS (Navipedia: Reference Frames in GNSS)
*[ENU]: East-North-Up — local tangent plane coordinate system centred on a receiver position

<!-- Signal bands -->
*[L1]: GPS/Galileo L1 band — centre frequency 1575.42 MHz (Navipedia: GPS Signal Plan)
*[L2]: GPS L2 band — centre frequency 1227.60 MHz (Navipedia: GPS Signal Plan)
*[L5]: GPS/Galileo L5/E5a band — centre frequency 1176.45 MHz, modernised civil signal

<!-- Software tools -->
*[uv]: Fast Python package manager written in Rust — replaces pip, pip-tools, virtualenv
*[ruff]: Fast Python linter and formatter written in Rust — replaces flake8, black, isort
*[MkDocs]: Static site generator for project documentation from Markdown
*[PyPI]: Python Package Index — public Python package repository
