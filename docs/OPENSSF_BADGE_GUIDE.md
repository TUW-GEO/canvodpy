# OpenSSF best practices badge application guide

## Overview

The OpenSSF Best Practices Badge (formerly CII Best Practices) is a certification that demonstrates your project follows open source security and quality best practices.

**Application URL:** https://bestpractices.coreinfrastructure.org/

## Badge levels

1. **Passing** (60%+ criteria) - Basic best practices
2. **Silver** (100% passing + additional criteria) - Advanced practices
3. **Gold** (100% silver + highest standards) - Exemplary practices

## How to apply

### Step 1: Create account
1. Go to https://bestpractices.coreinfrastructure.org/
2. Sign in with GitHub
3. Click "Add Project"
4. Enter: `https://github.com/nfb2021/canvodpy`

### Step 2: Complete questionnaire

The badge requires filling out criteria in these categories:

#### Basics (13 criteria)
- [x] Project website (https://canvodpy.eu/)
- [x] Basic documentation (README.md with clear description)
- [x] FLOSS license (Apache 2.0)
- [ ] Change control (public version control - GitHub)
- [x] Bug reporting process (GitHub Issues)
- [x] Security reporting process (SECURITY.md)

#### Change control (11 criteria)
- [x] Public version control (GitHub)
- [x] Unique version numbering (semantic versioning)
- [x] Release notes (CHANGELOG.md)
- [x] Contributors file (CONTRIBUTORS.md)

#### Quality (17 criteria)
- [x] Coding standards (ruff, PEP 8)
- [x] Automated test suite (pytest on Linux, macOS and Windows)
- [x] Code coverage (test_coverage.yml workflow)
- [x] Build reproducibility (uv.lock, pinned dependencies)
- [x] Continuous integration (GitHub Actions, `.github/workflows/`)

#### Security (21 criteria)
- [x] Security policy (SECURITY.md) ✨ newly added
- [x] Vulnerability disclosure process (SECURITY.md)
- [ ] Secure development knowledge (document that developers know secure coding)
- [x] Static analysis (ruff in `code_quality.yml`, CodeQL in `codeql.yml`)
- [x] Dynamic analysis (pytest, integration tests)
- [x] Dependency management (uv, Dependabot)

#### Analysis (6 criteria)
- [x] Static analysis enabled (ruff in CI)
- [x] Memory safety language (Python)
- [ ] Address sanitizers (not applicable for Python)

## Current status estimate

Based on canvodpy's current state:

### ✅ Already passing (estimated: ~70%)

**Basics:**
- ✅ Website with basic project info
- ✅ Clear description (README.md)
- ✅ OSI-approved license (Apache 2.0)
- ✅ Public version control (GitHub)
- ✅ Issue tracking (GitHub Issues)
- ✅ Distributed version control (Git)

**Change Control:**
- ✅ Semantic versioning
- ✅ CHANGELOG.md
- ✅ Release process (release.yml)
- ✅ Individual commit messages

**Quality:**
- ✅ Coding standards (ruff with 50+ rule sets, PEP 8 compliant)
- ✅ Type checking (ty with type budget enforcement)
- ✅ Test suite (pytest on Linux, macOS and Windows, with coverage)
- ✅ Test coverage (test_coverage.yml)
- ✅ CI/CD (GitHub Actions: tests, coverage, code quality, CodeQL, docs quality, FAIR, releases)
- ✅ Reproducible builds (uv.lock with pinned dependencies)
- ✅ Pre-commit hooks (ruff, ty, conventional commits)

**Security:**
- ✅ Vulnerability disclosure (SECURITY.md) ✨ New
- ✅ Dependency updates (Dependabot + uv.lock)
- ✅ Static analysis (ruff linting, CodeQL)
- ✅ Type safety (ty type checker)
- ✅ OpenSSF Scorecard (scorecard.yml) ✨ New

### 📝 Needs documentation

**Basics:**
- [ ] Document how to obtain help (add to CONTRIBUTING.md)
- [ ] Roadmap or project plans (could add to docs)

**Security:**
- [ ] Document that key developers know secure coding practices
- [ ] Document secure delivery method (signed releases, checksums)
- [ ] Document how to verify downloaded software

**Analysis:**
- [ ] Document static analysis tools used
- [ ] Document dynamic analysis results

### ⚙️ Needs Implementation

**Security:**
- [ ] Enable GitHub security advisories
- [ ] Add SPDX license identifiers to all source files (have REUSE.toml, need to verify)
- [ ] Two-factor authentication for all committers
- [ ] Signed releases (GPG/Sigstore)

## Quick wins (do these first)

### 1. Enable GitHub security features
```bash
# In GitHub repo settings:
Settings → Security → Enable:
  - Dependabot alerts ✓ (already enabled)
  - Dependabot security updates ✓
  - Code scanning alerts (via scorecard.yml) ✓
  - Secret scanning
```

### 2. Add security documentation to CONTRIBUTING.md
Add a section referencing SECURITY.md and secure coding practices.

### 3. Create SECURITY_PRACTICES.md
Document that developers follow secure coding practices:
- Input validation
- Error handling
- Dependency management
- Code review process

### 4. Verify REUSE compliance
```bash
just check-reuse
```

### 5. Add release verification
- Generate checksums for releases (SHA256)
- Consider signing releases with GPG or Sigstore

## Application process timeline

1. **Week 1:** Fill out questionnaire (~2-3 hours)
2. **Week 2:** Address gaps (documentation, process improvements)
3. **Week 3:** Request badge review
4. **Week 4:** Respond to reviewer feedback
5. **Week 5:** Receive badge 🎉

## Maintaining the badge

Once obtained, you must:
- Update badge status annually
- Keep criteria met as project evolves
- Document new security practices

## Resources

- **Badge Criteria:** https://bestpractices.coreinfrastructure.org/criteria
- **Getting Started Guide:** https://bestpractices.coreinfrastructure.org/en/projects/1
- **Examples:** Search GitHub for "best practices badge" to see other projects

## Next steps

1. **Create account** at bestpractices.coreinfrastructure.org
2. **Add canvodpy project**
3. **Start questionnaire** (save progress frequently)
4. **Address gaps** from "Needs Documentation" and "Needs Implementation" sections above
5. **Request review** once you're at 100%
6. **Add badge to README** once approved

## Badge markdown (add after approval)

```markdown
[![OpenSSF Best Practices](https://bestpractices.coreinfrastructure.org/projects/XXXXX/badge)](https://bestpractices.coreinfrastructure.org/projects/XXXXX)
```

Replace `XXXXX` with your project ID from the badge system.

---

**Note:** With SECURITY.md and scorecard.yml added, canvodpy is now much closer to meeting all the criteria.
