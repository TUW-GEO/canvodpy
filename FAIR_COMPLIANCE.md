# FAIR Compliance Status — canvodpy

## 1. Is there a FAIR certificate?

**For software: No.** There is no recognized, formal "FAIR certificate" for software as of 2026. The GO FAIR Foundation has a "Pioneer Program" in early development, but it is not operational. No organization currently grants a FAIR software certification.

**For data produced by software: No** (for individual datasets). **CoreTrustSeal** exists but certifies *repositories* (Zenodo, PANGAEA), not individual datasets. There is no certificate you can obtain for a specific dataset your software produces.

**What exists instead:** Self-assessment tools and compliance badges:

| Tool | Type | What it checks |
|------|------|----------------|
| [howfairis](https://github.com/fair-software/howfairis) | Automated CLI | 5 recommendations: repo, license, registry, citation, checklist |
| [FAIR Software Checklist](https://fairsoftwarechecklist.net/) | Web self-assessment | 15 questions across F/A/I/R |
| [FAIRsoft Evaluator](https://academic.oup.com/bioinformatics/article/40/8/btae464/7717992) | Automated (web) | FAIR4RS-derived indicators from registries |
| [F-UJI](https://www.f-uji.net/) | Automated (REST API) | FAIR compliance of datasets given a DOI |
| [fair-software.eu badge](https://fair-software.eu/) | Badge for README | Visual compliance indicator |

---

## 2. The FAIR4RS Principles

The authoritative standard is **FAIR4RS Principles v1.0** (RDA, 2022; [doi:10.1038/s41597-022-01710-x](https://www.nature.com/articles/s41597-022-01710-x)), adapted specifically for research software.

### Findable

| Principle | Requirement | Software | Data produced by software |
|-----------|-------------|----------|--------------------------|
| **F1** | Globally unique and persistent identifier | DOI via Zenodo or SWHID via Software Heritage per release. A GitHub URL alone is not sufficient. | Each output dataset needs its own DOI or persistent identifier. |
| **F1.1** | Components assigned distinct identifiers | In a monorepo, each separately distributed package should ideally have its own identifier. | Sub-datasets or different data products should have distinct identifiers. |
| **F1.2** | Different versions assigned distinct identifiers | Each release gets its own DOI. Zenodo's GitHub integration does this automatically. | Different versions of derived datasets should be identifiable separately. |
| **F2** | Rich metadata | `codemeta.json` and/or `CITATION.cff` with: name, description, authors, keywords, license, programming language, dependencies, date. | CF conventions for netCDF, ISO 19115 for geospatial data. |
| **F3** | Metadata include the identifier | The DOI or SWHID must appear in the metadata files themselves. | Dataset metadata must link to the dataset's own PID. |
| **F4** | Metadata are searchable and indexable | Register in searchable registries: PyPI, conda-forge, Research Software Directory. Metadata should be machine-readable (JSON-LD via CodeMeta). | Deposit in indexed repositories (Zenodo, PANGAEA) that expose metadata via OAI-PMH or DataCite APIs. |

### Accessible

| Principle | Requirement | Software | Data produced by software |
|-----------|-------------|----------|--------------------------|
| **A1** | Retrievable by identifier using standardized protocol | DOI must resolve via HTTPS to a downloadable landing page. Zenodo and PyPI satisfy this. | Data DOIs must resolve to downloadable data via HTTPS. |
| **A1.1** | Protocol is open, free, universally implementable | HTTPS satisfies this. No proprietary protocols or paid memberships. | Same. |
| **A1.2** | Protocol allows authentication where necessary | For open-source software, trivially satisfied. | If data requires authentication (embargo, sensitive data), protocol must support it. |
| **A2** | Metadata accessible even when software is unavailable | Metadata in Zenodo, Software Heritage, and PyPI persist even if GitHub repo is deleted. | Dataset metadata must persist even if data itself is removed. Zenodo guarantees this. |

### Interoperable

| Principle | Requirement | Software | Data produced by software |
|-----------|-------------|----------|--------------------------|
| **I1** | Reads, writes, exchanges data in domain-standard formats | Read RINEX (community standard), write netCDF with CF conventions, use standard CRS. | Output must use domain-standard formats: netCDF-4/HDF5 with CF conventions, standard variable names, UDUNITS. |
| **I2** | Qualified references to other objects | Document dependencies with version constraints (pyproject.toml), reference related datasets, link to publications. Use URIs. | Data should reference the software that produced it, input data sources, and related publications. |

### Reusable

| Principle | Requirement | Software | Data produced by software |
|-----------|-------------|----------|--------------------------|
| **R1** | Described with accurate and relevant attributes | Rich metadata: description, keywords, programming language, OS compatibility, funding, related publications. | Spatial/temporal coverage, resolution, processing level, quality flags. |
| **R1.1** | Clear and accessible license | OSI-approved license in LICENSE file. Machine-readable SPDX identifier in pyproject.toml, CITATION.cff, codemeta.json. | Data must have a clear license (CC-BY-4.0, CC0). May differ from software license. |
| **R1.2** | Detailed provenance | Who wrote it, when, what it derived from, version history (CHANGELOG.md), contribution history. | Which software version produced it, which input data, processing parameters, timestamps. |
| **R2** | Qualified references to other software | Explicit, versioned dependency declarations in pyproject.toml. | Data should reference the software tools used (with version and DOI). |
| **R3** | Meets domain-relevant community standards | PEP 8, type hints, API documentation, scientific Python packaging conventions. For geodesy: standard geodetic libraries and conventions. | CF conventions, ACDD (Attribute Convention for Data Discovery), ISO 19115 for geospatial metadata. |

---

## 3. canvodpy compliance status

### In place

- [x] Public GitHub repository with version control
- [x] Apache-2.0 LICENSE
- [x] `CITATION.cff` with DOI and ORCID
- [x] Zenodo DOI (10.5281/zenodo.18496233)
- [x] Published on PyPI: `uv add canvodpy`, or any `canvod-*` package on its own
- [x] `CHANGELOG.md`, `CONTRIBUTING.md`
- [x] `pyproject.toml` with versioned dependencies
- [x] Semantic versioning
- [x] Domain-standard I/O (RINEX input, xarray/netCDF ecosystem)
- [x] Code style enforcement (ruff)

### Missing

| Gap | FAIR principle | Action |
|-----|---------------|--------|
| ~~`codemeta.json`~~ | ~~F2, F4~~ | Done — `codemeta.json` exists at repo root |
| Software Heritage archival | F1, A2 | Submit via [archive.softwareheritage.org/save](https://archive.softwareheritage.org/save/) to get a SWHID |
| `howfairis` badge | All | Run `howfairis` on the repo, add badge to README |
| `.zenodo.json` | F2 | Control communities, grants, related identifiers beyond CITATION.cff |
| Output data provenance | R1.2, I2 | Embed in netCDF outputs: software name, version, DOI, processing date, input references |
| Output data standards | I1, R3 | netCDF-4 with CF conventions (standard_name, units), ACDD global attributes |
| Output data license | R1.1 | Explicitly license output data (e.g., CC-BY-4.0) |

---

## 4. Practical steps

Based on the FAIR-BioRS guidelines ([doi:10.1038/s41597-023-02463-x](https://www.nature.com/articles/s41597-023-02463-x)):

1. Generate `codemeta.json` and commit to root
2. Archive on Software Heritage (one-time "Save Code Now")
3. Publish to PyPI
4. Run `howfairis`, add badge to README
5. Add ACDD/CF provenance attributes to all netCDF outputs
6. When depositing output datasets, give them their own DOIs referencing canvodpy's DOI as "isDerivedFrom"

---

## 5. Organizations and standards

| Organization | Role | Certifies? |
|-------------|------|------------|
| [CoreTrustSeal](https://www.coretrustseal.org/) | Certifies data repositories | Yes (repositories only) |
| [GO FAIR Foundation](https://www.gofairfoundation.org/) | Promotes FAIR implementation | Not yet (Pioneer Program in development) |
| [RDA](https://www.rd-alliance.org/) | Published FAIR4RS Principles | No (principles only) |
| [ReSA](https://www.researchsoft.org/) | Co-convened FAIR4RS WG | No |
| [Software Heritage](https://www.softwareheritage.org/) | Archives source code, provides SWHIDs (ISO/IEC 18670) | No (archival infrastructure) |
| [Netherlands eScience Center](https://www.esciencecenter.nl/) | Created fair-software.eu, howfairis | No (assessment tools) |

---

## References

- [GO FAIR - FAIR Principles](https://www.go-fair.org/fair-principles/)
- [FAIR4RS Principles v1.0 (Zenodo)](https://zenodo.org/records/6623556)
- [Introducing the FAIR Principles for research software (Nature Scientific Data, 2022)](https://www.nature.com/articles/s41597-022-01710-x)
- [FAIR-BioRS Guidelines (Nature Scientific Data, 2023)](https://www.nature.com/articles/s41597-023-02463-x)
- [fair-software.eu](https://fair-software.eu/)
- [howfairis (GitHub)](https://github.com/fair-software/howfairis)
- [FAIR Software Checklist](https://fairsoftwarechecklist.net/)
- [F-UJI](https://www.f-uji.net/)
- [FAIR-IMPACT Assessment Tools](https://fair-impact.eu/fair-assessment-tools)
- [CodeMeta Project](https://codemeta.github.io/)
- [CF Conventions](https://cfconventions.org/)
- [CODE beyond FAIR (Inria, 2025)](https://inria.hal.science/hal-04930405v2)
