# Free and open source software (FOSS) principles

## Overview

**canvodpy** is developed as Free and Open Source Software (FOSS) following the principles established by the Free Software Foundation[^1] and endorsed by the Open Source Initiative.[^2] This commitment ensures the software remains freely accessible, modifiable, and redistributable, enabling transparent scientific research and fostering collaborative development within the GNSS and atmospheric science communities.

## Definitions and distinctions

### Free software

Free software, as defined by the Free Software Foundation, guarantees users four essential freedoms:[^1]

0. **Freedom to run** the program for any purpose
1. **Freedom to study** how the program works and change it
2. **Freedom to redistribute** copies
3. **Freedom to distribute** modified versions

The term "free" refers to liberty (*libre*), not price (*gratis*), emphasizing user autonomy over software control.

### Open source software

Open source software, as characterized by the Open Source Initiative, emphasizes development methodology and source code availability.[^2] The Open Source Definition requires:

- Free redistribution without restrictions
- Source code availability and modification rights
- Derived works and modifications permitted
- No discrimination against persons, groups, or fields of endeavor
- License distribution without requiring additional agreements
- Technology neutrality

### Relationship and convergence

While historically distinguished by philosophical emphasis (free software prioritizing user freedom, open source emphasizing practical benefits), the vast majority of licenses satisfy both definitions.[^3] Modern practice increasingly treats these as complementary perspectives on the same software licensing paradigm, hence the unified term "FOSS" (Free and Open Source Software) or "FLOSS" (Free/Libre and Open Source Software).

## License: Apache License 2.0

**canvodpy** is licensed under the **Apache License, Version 2.0**,[^4] a permissive FOSS license approved by both the Free Software Foundation[^5] and Open Source Initiative.[^6]

### Key provisions

The Apache 2.0 license provides:

- **Permissive use rights**: Commercial and non-commercial use without restrictions
- **Modification freedom**: Unlimited source code modification and distribution
- **Patent grant**: Explicit patent license from contributors to users
- **Trademark protection**: Project name and marks remain protected
- **Attribution requirements**: Copyright and license notices must be retained
- **No copyleft**: Modified versions may use different licenses

### Rationale for selection

Apache 2.0 was selected for several reasons relevant to scientific software:

1. **Patent protection**: Each contributor grants users a license to the contributor's patents that the contribution uses (section 3)[^4]
2. **Clear terms**: Well-documented license reduces legal ambiguity[^4]
3. **Permissive integration**: Compatible with most other FOSS licenses, enabling ecosystem integration

## FOSS compliance frameworks

### FAIR software principles

The FAIR principles, originally developed for research data[^17], have been adapted for research software[^18] to enhance:

- **Findability**: Persistent identifiers and metadata enable software discovery
- **Accessibility**: Open access and clear licenses facilitate software reuse
- **Interoperability**: Standards-based design supports integration
- **Reusability**: Documentation and licensing enable legitimate reuse

**canvodpy** implements FAIR software through:

- GitHub repository with persistent URL
- Apache 2.0 open source license
- Zenodo DOI: [`10.5281/zenodo.19445061`](https://doi.org/10.5281/zenodo.19445061)
- Citation metadata (CITATION.cff, codemeta.json)
- OpenSSF Best Practices certification
- Automated FAIR compliance checking

**Status**: 5/5 FAIR recommendations met

**Reference**: [FAIR Software Compliance Summary](FAIR_IMPLEMENTATION_SUMMARY.md)

### OpenSSF best practices

The Open Source Security Foundation (OpenSSF) Best Practices badge program[^19] establishes security and quality criteria for FOSS projects. The program promotes:

- **Security awareness**: Vulnerability reporting and response procedures
- **Code quality**: Static analysis, testing, and code review practices
- **Development transparency**: Public version control and issue tracking
- **Release integrity**: Signed releases and supply chain security

**canvodpy** earned the OpenSSF Best Practices badge (passing level) by demonstrating:

- Security policy with coordinated disclosure (SECURITY.md)
- Static analysis (ruff, ty) and dynamic testing (pytest)
- Public development on GitHub with issue tracking
- Automated security scanning (OpenSSF Scorecard)
- Reproducible builds with locked dependencies

**Badge**: [OpenSSF Best Practices Project 12329](https://www.bestpractices.dev/projects/12329)

**Reference**: [OpenSSF Badge Implementation Guide](OPENSSF_BADGE_GUIDE.md)

### Software Heritage archival

Software Heritage[^20] provides permanent archival of public source code, ensuring long-term preservation independently of hosting platform stability. Anyone can ask Software Heritage to archive a public repository with [Save Code Now](https://archive.softwareheritage.org/save/).

## Community and governance

### Contribution model

**canvodpy** welcomes contributions following established FOSS development patterns:

- **Issue tracking**: Bug reports and feature requests on GitHub Issues
- **Pull requests**: Code contributions via GitHub Pull Requests
- **Code review**: Maintainer review before integration
- **CI validation**: Automated testing verifies changes
- **License agreement**: Contributors grant rights under Apache 2.0

**Reference**: [CONTRIBUTING.md](CONTRIBUTING.md)

### Maintenance and support

The project is actively maintained with:

- Regular dependency updates and security patches
- Responsive issue triage (target: 7 days for initial response)
- Semantic versioning for API stability
- Long-term support considerations for published research

### Attribution and citation

Academic users should cite **canvodpy** using the provided citation metadata:

- **Citation file**: [CITATION.cff](../CITATION.cff)
- **Zenodo record**: [`10.5281/zenodo.19445061`](https://doi.org/10.5281/zenodo.19445061)

Proper citation ensures software developers receive academic credit, addressing a key sustainability challenge for research software.[^15]

## Future directions

### Planned enhancements

- **PyPI publication**: Complete 5/5 FAIR compliance with package registry distribution
- **Silver badge**: Pursue OpenSSF Best Practices silver level certification
- **Community growth**: Expand contributor base and governance structures
- **Sustainability**: Explore funding mechanisms for long-term maintenance

### Commitments

**canvodpy** commits to:

- Maintaining open source availability under Apache 2.0 or compatible license
- Preserving public development history and decision documentation
- Supporting reproducible research through stable, well-documented releases
- Engaging with the scientific software community through workshops and publications

---

## Additional resources

- **FAIR Software**: [fair-software.eu](https://fair-software.eu/)
- **OpenSSF**: [openssf.org](https://openssf.org/)
- **Software Heritage**: [softwareheritage.org](https://www.softwareheritage.org/)
- **FORCE11 Software Citation Principles**: [force11.org/software-citation-principles](https://force11.org/software-citation-principles)
- **Journal of Open Source Software**: [joss.theoj.org](https://joss.theoj.org/)
- **Research Software Alliance**: [researchsoft.org](https://www.researchsoft.org/)

---

*This document is maintained as part of canvodpy's commitment to transparent, reproducible, and collaborative scientific software development.*

[^1]: Free Software Foundation. "What is Free Software?" [https://www.gnu.org/philosophy/free-sw.html](https://www.gnu.org/philosophy/free-sw.html)
[^2]: Open Source Initiative. "The Open Source Definition." [https://opensource.org/osd](https://opensource.org/osd)
[^3]: Stallman, R. "Why Open Source Misses the Point of Free Software." [https://www.gnu.org/philosophy/open-source-misses-the-point.html](https://www.gnu.org/philosophy/open-source-misses-the-point.html)
[^4]: Apache Software Foundation. "Apache License, Version 2.0." (2004). [https://www.apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0)
[^5]: Free Software Foundation. "Various Licenses and Comments about Them." [https://www.gnu.org/licenses/license-list.html#apache2](https://www.gnu.org/licenses/license-list.html#apache2)
[^6]: Open Source Initiative. "Apache License 2.0." [https://opensource.org/licenses/Apache-2.0](https://opensource.org/licenses/Apache-2.0)
[^15]: Smith, A. M., Katz, D. S., Niemeyer, K. E., & FORCE11 Software Citation Working Group (2016). "Software Citation Principles." *PeerJ Computer Science*, 2, e86. [https://doi.org/10.7717/peerj-cs.86](https://doi.org/10.7717/peerj-cs.86)
[^17]: Wilkinson, M. D., et al. (2016). "The FAIR Guiding Principles for Scientific Data Management and Stewardship." *Scientific Data*, 3, 160018. [https://doi.org/10.1038/sdata.2016.18](https://doi.org/10.1038/sdata.2016.18)
[^18]: Barker, M., et al. (2022). "Introducing the FAIR Principles for Research Software." *Scientific Data*, 9, 622. [https://doi.org/10.1038/s41597-022-01710-x](https://doi.org/10.1038/s41597-022-01710-x)
[^19]: OpenSSF. "OpenSSF Best Practices Badge Program." [https://www.bestpractices.dev/](https://www.bestpractices.dev/)
[^20]: Di Cosmo, R., & Zacchiroli, S. (2017). "Software Heritage: Why and How to Preserve Software Source Code." *iPRES 2017: 14th International Conference on Digital Preservation*. [https://hal.science/hal-01590958](https://hal.science/hal-01590958)
