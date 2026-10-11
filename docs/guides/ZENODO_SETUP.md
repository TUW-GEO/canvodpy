---
title: Setting Up DOI and Citations (Zenodo)
description: Make canvodpy citable with DOI for FAIR science
---

# DOI and Citations Setup (Zenodo)

Make canvodpy properly citable with a permanent DOI for academic papers using **Zenodo + CITATION.cff**.

---

## Zenodo

[Zenodo](https://zenodo.org) is a research data repository operated by CERN.

<div class="grid cards" markdown>

-   :fontawesome-solid-link: &nbsp; **Automatic DOI**

    ---

    Each GitHub release automatically gets a permanent DOI
    (`10.5281/zenodo.XXXXX`). No manual uploads.

-   :fontawesome-solid-archive: &nbsp; **Permanent Archival**

    ---

    CERN guarantees 20+ years of preservation.
    Every release is archived forever, so it stays reproducible.

-   :fontawesome-solid-magnifying-glass: &nbsp; **FAIR Compliant**

    ---

    Findable · Accessible · Interoperable · Reusable.
    Searchable by researchers worldwide, indexed by Google Scholar.

-   :fontawesome-brands-github: &nbsp; **GitHub Integration**

    ---

    Link your repo once. Every subsequent GitHub release triggers
    automatic archival and DOI minting.

</div>

---

## How It Works

### 1. Initial Setup (One-Time)

You link your GitHub repo to Zenodo:
- Zenodo watches for new releases
- No manual uploads needed

### 2. Every Release

```bash
just release canvod-store=1.1.0 canvodpy=1.1.0   # release commit on release/v1.1.0: open a PR, merge it
# then, on the merged main:
just tag-release && git push origin v1.1.0 canvod-store-v1.1.0
```

Only the canvodpy tag (`v1.1.0`) creates a GitHub release, so Zenodo
archives one version per canvodpy release; package tags get none.

**Automatic workflow:**
1. GitHub creates release v0.1.0
2. Zenodo detects new release
3. Zenodo archives the release
4. Zenodo mints DOI: `10.5281/zenodo.XXXXX`
5. Zenodo creates citation metadata

### 3. Users Cite Your Work

Researchers can cite:
```
Bader, N. F. (2026). canvodpy: GNSS Vegetation Optical Depth Analysis (v0.1.0).
Zenodo. https://doi.org/10.5281/zenodo.XXXXX
```

**Version-specific DOIs:**
- v0.1.0 $\rightarrow$ DOI: 10.5281/zenodo.12345
- v0.2.0 $\rightarrow$ DOI: 10.5281/zenodo.12346
- Concept DOI $\rightarrow$ DOI: 10.5281/zenodo.12344 (always latest)

---

## Step 1: Create CITATION.cff *(Done)*

`CITATION.cff` enables the **"Cite this repository"** button on GitHub, exports to BibTeX/APA/EndNote, and provides metadata for Zenodo.

!!! tip "Add your ORCID iD"
    Edit `CITATION.cff` line 14 and add your ORCID identifier.
    Get one at [orcid.org/register](https://orcid.org/register); it links your publications to your researcher profile.

---

## Step 2: Connect GitHub to Zenodo

### 2.1: Create Zenodo Account

1. Go to: https://zenodo.org
2. Click "Sign up"
3. **Important:** Sign up with GitHub!
   - Click "Log in with GitHub"
   - This enables automatic integration

### 2.2: Enable Repository on Zenodo

1. After logging in, go to: https://zenodo.org/account/settings/github/
2. Find `nfb2021/canvodpy` in the list
3. **Toggle ON** the switch next to it
4. Zenodo is now watching for releases!

### 2.3: Verify Connection

- Should see: "✓ Enabled" next to canvodpy
- Zenodo will archive next release

---

## Step 3: Create First Release

### Option A: Test with Beta Release

```bash
git tag -a v0.1.0b2 -m "Test Zenodo DOI creation"
git push origin v0.1.0b2
```

- Creates TestPyPI release
- Zenodo creates DOI
- You can test the process safely

### Option B: Production Release

```bash
just release canvodpy=0.1.0 canvod-readers=0.1.0 ...   # open a PR, merge it
# then, on the merged main:
just tag-release && git push origin v0.1.0 canvod-readers-v0.1.0 ...
```

- Creates the GitHub release; PyPI follows with `gh workflow run publish_pypi.yml --ref v0.1.0`
- Zenodo creates DOI
- This is the "real" first citable version

### After Release

1. Go to: https://zenodo.org/account/settings/github/repository/nfb2021/canvodpy
2. You'll see your release listed
3. Click to view the DOI
4. Copy the DOI badge markdown

**Example DOI badge:**
```markdown
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.12345.svg)](https://doi.org/10.5281/zenodo.12345)
```

---

## Step 4: Add DOI Badge to README

Add to `README.md` (after other badges):

```markdown
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXX)
```

Replace `XXXXX` with your actual Zenodo ID.

**Tip:** Use the "concept DOI" (always points to latest version)

---

## Step 5: Update Documentation

Add citation section to `README.md`:

```markdown
## Citing canvodpy

If you use canvodpy in your research, please cite:

Bader, N. F. (2026). canvodpy: GNSS Vegetation Optical Depth Analysis (v0.1.0).
Zenodo. https://doi.org/10.5281/zenodo.XXXXX

BibTeX:
\`\`\`bibtex
@software{bader2026canvodpy,
  author       = {Bader, Nicolas François},
  title        = {canvodpy: GNSS Vegetation Optical Depth Analysis},
  year         = 2026,
  publisher    = {Zenodo},
  version      = {v0.1.0},
  doi          = {10.5281/zenodo.XXXXX},
  url          = {https://doi.org/10.5281/zenodo.XXXXX}
}
\`\`\`
```

---

## How Citations Work

### For Researchers Using Your Package

**From GitHub:**
1. Click "Cite this repository" (top right)
2. Choose format (APA, BibTeX, etc.)
3. Copy citation

**From Zenodo:**
1. Visit Zenodo DOI link
2. Click "Export" $\rightarrow$ Choose format
3. Copy citation

### For Papers

Researchers cite specific versions:

**Correct:**
> "We used canvodpy v0.1.0 (Bader, 2026) for VOD calculations."

**Reference:**
> Bader, N. F. (2026). canvodpy v0.1.0. Zenodo. https://doi.org/10.5281/zenodo.12345

**Why version-specific?**
- Reproducibility: v0.1.0 code is archived forever
- Transparency: Readers know exactly what was used
- FAIR principles: Findable specific version

### Concept DOI vs Version DOI

**Concept DOI** (10.5281/zenodo.12344):
- Always points to latest version
- Use for: General citations, badges

**Version DOI** (10.5281/zenodo.12345):
- Points to specific version (v0.1.0)
- Use for: Research papers (reproducibility)

---

## Benefits

| Category | What you get |
|----------|-------------|
| Academic recognition | Citable software output; the DOI is trackable in citations |
| ORCID integration | Links code releases to your researcher profile |
| FAIR compliance | Findable, Accessible, Interoperable, Reusable |
| Permanent archival | CERN preserves every release indefinitely |
| Trusted repository | Used by CERN, NASA, and ESA; accepted by all journals |

---

## Troubleshooting

??? failure "Repo not visible on Zenodo"
    1. Ensure you logged in **with GitHub** (not email)
    2. Check the repo is **public**: Zenodo only indexes public repos
    3. Log out and back in; sync can take a few minutes

??? failure "No DOI created for a release"
    1. Verify the toggle is **ON** at [zenodo.org/account/settings/github/](https://zenodo.org/account/settings/github/)
    2. Ensure the GitHub release is **published** (not a draft)
    3. Check your Zenodo email for error notifications

??? question "How to update citation metadata?"
    Update `CITATION.cff`, then create a new release.
    Zenodo reads the updated file for the new DOI automatically.

??? question "Can I get a DOI for old releases?"
    No. Zenodo only archives releases created **after** the integration was enabled.
    You can create new patch/beta releases to archive historical code states.

---

## Example: How It Looks

### On GitHub

**Cite button:**
```
[Cite this repository ▼]
├── APA
├── BibTeX
└── More formats...
```

### On Zenodo

**Record page:**
```
DOI: 10.5281/zenodo.12345
Title: canvodpy: GNSS Vegetation Optical Depth Analysis
Authors: Nicolas François Bader
Version: v0.1.0
Publication date: 2026-02-04
Resource type: Software
License: Apache-2.0

[Download] [Cite] [Share] [Export]
```

### In Papers

**Methods section:**
> "VOD was calculated using canvodpy v0.1.0 (Bader, 2026),
> an open-source Python package for GNSS-based vegetation analysis."

**References:**
> Bader, N. F. (2026). canvodpy: GNSS Vegetation Optical Depth Analysis (v0.1.0).
> Zenodo. https://doi.org/10.5281/zenodo.12345

---

## Additional Metadata (Optional)

### .zenodo.json

For advanced metadata customization, create `.zenodo.json`:

```json
{
  "title": "canvodpy: GNSS Vegetation Optical Depth Analysis",
  "description": "Python package for VOD calculation from GNSS SNR data",
  "creators": [
    {
      "name": "Bader, Nicolas François",
      "affiliation": "TU Wien",
      "orcid": "0000-0000-0000-0000"
    }
  ],
  "keywords": ["GNSS", "VOD", "vegetation", "remote sensing"],
  "license": "Apache-2.0",
  "communities": [
    {"identifier": "zenodo"}
  ]
}
```

**Note:** CITATION.cff is usually sufficient!

---

## Resources

- [Zenodo Homepage](https://zenodo.org)
- [Zenodo GitHub Integration Guide](https://docs.github.com/en/repositories/archiving-a-github-repository/referencing-and-citing-content)
- [CITATION.cff Format](https://citation-file-format.github.io/)
- [ORCID Registration](https://orcid.org/register)
- [FAIR Principles](https://www.go-fair.org/fair-principles/)
- [Making Software Citable](https://guides.github.com/activities/citable-code/)

---

## Quick Start Checklist

- [ ] Get ORCID iD (if you don't have one)
- [ ] Update CITATION.cff with your ORCID
- [ ] Create Zenodo account (log in with GitHub)
- [ ] Enable canvodpy on Zenodo settings
- [ ] Create first release (test with beta or go production)
- [ ] Copy DOI badge to README
- [ ] Add citation section to README
- [ ] Update documentation with citation instructions

---

**Questions?** Check [Zenodo help](https://help.zenodo.org/) or ask in discussions!
