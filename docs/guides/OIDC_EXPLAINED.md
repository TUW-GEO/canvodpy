---
title: OIDC Trusted Publishing Explained
description: Deep dive into how OIDC authentication works for PyPI publishing
---

# How OIDC trusted publishing works

!!! abstract "Summary"
    OIDC lets GitHub Actions publish to PyPI **without passwords or long-lived tokens**.
    It uses cryptographic JWT proofs that expire in 10 minutes, so no secrets are stored.

---

## Traditional versus OIDC

<div class="grid" markdown>

!!! failure "API Tokens (old way)"
    - Long-lived tokens (months/years)
    - If GitHub is breached, token leaks
    - Broad permissions (all packages)
    - Need manual rotation
    - Can be accidentally committed to git

!!! success "OIDC (2026 standard)"
    - Short-lived JWT proof (10 minutes)
    - No stored secrets anywhere
    - Scoped to a specific repository and workflow
    - Zero rotation overhead
    - Cryptographically verified identity

</div>

---

## The traditional way (API tokens)

```
You → Generate API token on PyPI → Store in GitHub Secrets → Workflow uses token
```

**Problems:**
- Long-lived tokens (months/years)
- If GitHub is compromised, token leaks
- Token has broad permissions (all packages)
- Need manual rotation
- Can be accidentally committed to git

---

## The OIDC way (2026 standard)

### Overview

OIDC (OpenID Connect) is an authentication protocol built on OAuth 2.0. Instead of storing long-lived tokens, it uses **short-lived cryptographic proofs** (JWT tokens).

### The flow

```
┌─────────────┐
│ Developer   │
│ git push    │
│ --tags      │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ GitHub Actions Workflow                                 │
│                                                         │
│ 1. Builds packages                                      │
│ 2. Requests JWT from GitHub OIDC provider              │
│ 3. GitHub generates signed JWT with workflow identity  │
│ 4. Sends JWT + packages to PyPI                        │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ PyPI Validation                                         │
│                                                         │
│ For each package:                                       │
│   ✓ Verify JWT signature (GitHub's public key)         │
│   ✓ Check JWT not expired (~10 min TTL)                │
│   ✓ Validate claims:                                    │
│     • repository: nfb2021/canvodpy ✓                    │
│     • workflow: publish_testpypi.yml ✓                  │
│     • environment: testpypi ✓                          │
│     • package name: canvod-readers ✓                    │
│                                                         │
│ All match? → PUBLISH                                    │
│ Mismatch?   → REJECT                                    │
└─────────────────────────────────────────────────────────┘
```

---

## Step by step

### 1. Registration (one-time setup)

You register a **trust relationship** on PyPI:

> "I trust GitHub Actions from repository `nfb2021/canvodpy`,
> specifically the workflow `publish_testpypi.yml` running in
> environment `testpypi`, to publish package `canvod-readers`"

**No secrets exchanged!** This just tells PyPI what to expect.

### 2. Workflow run

When you push a tag (`v0.1.0-beta.1`), the workflow runs:

```yaml
permissions:
  id-token: write  # ← Request OIDC JWT capability
```

### 3. The JWT is issued

GitHub's OIDC provider generates a JWT containing:

```json
{
  "iss": "https://token.actions.githubusercontent.com",
  "sub": "repo:nfb2021/canvodpy:environment:testpypi",
  "aud": "https://test.pypi.org",
  "repository": "nfb2021/canvodpy",
  "repository_owner": "nfb2021",
  "repository_owner_id": "93122788",
  "workflow": "publish_testpypi.yml",
  "workflow_ref": "nfb2021/canvodpy/.github/workflows/publish_testpypi.yml@refs/tags/v0.1.0-beta.1",
  "environment": "testpypi",
  "ref": "refs/tags/v0.1.0-beta.1",
  "iat": 1738677600,  // Issued at
  "exp": 1738678200   // Expires at (10 minutes later)
}
```

**Cryptographically signed** with GitHub's private key.

### 4. Publish action

The `pypa/gh-action-pypi-publish` action:
1. Retrieves the JWT from GitHub's OIDC provider
2. Bundles it with the package files
3. Sends to PyPI/TestPyPI upload endpoint

### 5. PyPI checks the token

PyPI receives the request and validates:

**1. Signature Verification**
```
✓ JWT signed by GitHub? (verify with GitHub's public key)
```

**2. Expiration Check**
```
✓ Current time < exp claim?
✓ iat claim reasonable?
```

**3. Claims Validation**
```
✓ repository == "nfb2021/canvodpy"?
✓ workflow == "publish_testpypi.yml"?
✓ environment == "testpypi"?
✓ Package name == "canvod-readers"? (matches upload)
```

**4. Trust Relationship Lookup**
```
✓ Is there a registered publisher matching these claims?
✓ Does the publisher have permission for this package?
```

**All pass?** $\rightarrow$ Package published.
**Any fail?** $\rightarrow$ `403 Forbidden` with detailed error

---

## Security properties

### No long-lived secrets

**Traditional tokens:**
- Valid for months/years
- If leaked, usable until manually revoked
- Broad permissions

**OIDC JWTs:**
- Valid for ~10 minutes
- Automatically expire
- Scoped to specific workflow + environment + package

### Cryptographic verification

**How JWT signatures work:**

1. GitHub has a **private key** (secret, never shared)
2. GitHub publishes a **public key** at `https://token.actions.githubusercontent.com/.well-known/jwks`
3. JWT is signed with private key
4. PyPI verifies signature with public key

**Why it's secure:**
- Only GitHub can create valid JWTs (has private key)
- Anyone can verify JWTs (public key is public)
- Forging a JWT requires private key (mathematically infeasible)

### Scoped Permissions

Each trust relationship is scoped to:

| Scope | Example | Purpose |
|-------|---------|---------|
| Repository | `nfb2021/canvodpy` | Only this repository can publish |
| Workflow | `publish_testpypi.yml` | Only this workflow file |
| Environment | `testpypi` | Only this environment |
| Package | `canvod-readers` | Only this PyPI package |

**Example attack prevention:**

- Can't use a JWT from a different repository
- Can't use JWT from different workflow
- Can't use JWT from different environment
- Can't publish to different package
- Can't replay expired JWT
- Can't modify JWT claims (signature breaks)

### Audit trail

GitHub records:
- Who triggered the workflow
- What tag/branch/commit
- When it ran
- What environment was used

PyPI records:
- Which JWT claims were used
- When publish occurred
- Which files were uploaded

**Full traceability:** "v0.1.0 was published by workflow X triggered by user Y at time Z"

---

## Why several publishers?

Each package needs its own trust relationship:

```
PyPI Trust Registry:
┌──────────────────┬─────────────────┬──────────────────────┬─────────┐
│ Package          │ Repository      │ Workflow             │ Env     │
├──────────────────┼─────────────────┼──────────────────────┼─────────┤
│ canvod-readers   │ nfb2021/canvodpy│ publish_testpypi.yml │ testpypi│
│ canvod-auxiliary       │ nfb2021/canvodpy│ publish_testpypi.yml │ testpypi│
│ canvod-grids     │ nfb2021/canvodpy│ publish_testpypi.yml │ testpypi│
│ ...              │ ...             │ ...                  │ ...     │
└──────────────────┴─────────────────┴──────────────────────┴─────────┘
```

**Why?** PyPI validates per-package:

> "Does this JWT have permission to publish THIS specific package?"

If you only register `canvodpy`, the workflow can't publish `canvod-readers`.

---

## GitHub environments

```yaml
environment: testpypi  # ← Why this matters
```

### Security benefits

**1. Protection Rules**
- Require manual approval before publish
- Limit to specific branches
- Add reviewers

**2. Secrets Scoping**
- Environment-specific secrets (if needed)
- Separate test vs production

**3. Audit & History**
- See all deployments to this environment
- Track who approved what
- Deployment logs

**4. OIDC Scoping**
- JWT includes environment name in claims
- Different environments = different publishers
- Example: `testpypi` environment $\rightarrow$ test.pypi.org
           `pypi` environment $\rightarrow$ pypi.org

---

## Common configuration mistakes

### 1. Mismatched environment name

**Workflow says:**
```yaml
environment: testpypi
```

**PyPI registered with:**
```
Environment: test-pypi  # ← Note the dash!
```

**Result:** the JWT is rejected (environment claim doesn't match)

### 2. Mismatched workflow file

**Workflow filename:**
```
.github/workflows/publish-testpypi.yml  # ← Note the dash!
```

**PyPI registered with:**
```
Workflow: publish_testpypi.yml  # ← Note the underscore!
```

**Result:** the JWT is rejected

### 3. Wrong repository owner

**Your GitHub username:** `nfb2021`
**PyPI registered with:** `NFB2021` (different case!)

**Result:** the JWT is rejected (the check is case-sensitive)

### 4. Package not registered

You set up OIDC for `canvodpy` but forgot `canvod-readers`.

**Result:** `canvodpy` publishes successfully, `canvod-readers` fails

---

## Advantages over other methods

### Compared with user name and password

| Method | OIDC | Username/Password |
|--------|------|-------------------|
| Security | Cryptographic | Password-based |
| Lifetime | 10 minutes | Forever (until changed) |
| Revocation | Automatic expiry | Manual change |
| MFA Compatible | Always | Sometimes |
| Audit Trail | Built-in | Manual logging |

### Compared with API tokens

| Method | OIDC | API Token |
|--------|------|-----------|
| Storage | None needed | GitHub Secrets |
| Rotation | Not needed | Manual (quarterly?) |
| Scope | Per-package | Account-wide |
| Leak Risk | Low (expires fast) | High (long-lived) |
| Setup | One-time registration | Generate + store |

---

## An analogy

**API Tokens = House Key**
- You give someone a key
- They can use it anytime
- If lost, anyone can use it
- Must change locks to revoke

**OIDC = Hotel Key Card**
- Hotel validates your identity (JWT)
- Issues temporary card (expires checkout time)
- Card only works for your room (scoped)
- Card automatically deactivates (expiration)
- Can't duplicate card (cryptographic signature)
- Full audit trail (who, when, what room)

---

## Further reading

- [PyPI Trusted Publishers Documentation](https://docs.pypi.org/trusted-publishers/)
- [OIDC Specification](https://openid.net/connect/)
- [GitHub OIDC Documentation](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect)
- [JWT.io - Debug JWTs](https://jwt.io/)
- [GitHub JWKS Endpoint](https://token.actions.githubusercontent.com/.well-known/jwks)

---

**Questions?** Open an issue or a discussion.
