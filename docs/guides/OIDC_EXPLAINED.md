---
title: OIDC Trusted Publishing Explained
description: How OIDC trusted publishing to PyPI works
---

# How OIDC trusted publishing works

!!! abstract "Summary"
    OIDC lets GitHub Actions publish to PyPI **without passwords or stored
    tokens**. The workflow proves its identity with a signed token from
    GitHub, and PyPI answers with an API token that is valid for 15 minutes.

---

## Stored API tokens versus OIDC

<div class="grid" markdown>

!!! failure "Stored API token"
    - Long-lived: valid until someone revokes it
    - Kept in GitHub secrets, from where it can leak
    - Rotated by hand

!!! success "Trusted publishing (OIDC)"
    - No secret stored anywhere
    - The API token PyPI issues expires after 15 minutes
    - Bound to one repository, workflow file, and environment

</div>

In the words of the [PyPI docs](https://docs.pypi.org/trusted-publishers/),
"PyPI's normal API tokens are long-lived." "Trusted Publishing avoids this
problem because the tokens minted expire automatically."

---

## The flow

OIDC (OpenID Connect) is an identity layer on OAuth 2.0. GitHub issues a
signed token (a JWT) that says which repository, workflow, and environment
a job runs in; PyPI checks it against the trusted publishers registered for
a project.

```
┌──────────────────────┐
│ Maintainer           │
│ gh workflow run      │
│ publish_pypi.yml     │
│ --ref v1.0.0         │
└──────┬───────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ GitHub Actions workflow                                 │
│                                                         │
│ 1. Builds the packages                                  │
│ 2. Requests a JWT from GitHub's OIDC provider           │
│ 3. Sends the JWT to PyPI                                │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ PyPI                                                    │
│                                                         │
│ ✓ Verifies the JWT signature (GitHub's public key)      │
│ ✓ Matches the claims against the trusted publishers:    │
│     • repository: TUW-GEO/canvodpy                      │
│     • workflow file: publish_pypi.yml                   │
│     • environment: pypi                                 │
│ → Issues an API token (15 minutes) for every project    │
│   with a matching publisher                             │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ The workflow uploads the packages with that API token   │
└─────────────────────────────────────────────────────────┘
```

---

## Step by step

### 1. Registration (one-time setup)

You register a **trusted publisher** for each project on PyPI. It says,
in effect, that GitHub Actions in repository `TUW-GEO/canvodpy`, workflow
`publish_pypi.yml`, environment `pypi`, may publish `canvod-readers`.

**No secrets are exchanged.** This only tells PyPI what to expect.

### 2. Workflow run

A maintainer starts the workflow on a release tag
(`gh workflow run publish_pypi.yml --ref v1.0.0`). Its publish job has:

```yaml
permissions:
  id-token: write  # ← may request an OIDC token
```

### 3. The token GitHub issues

GitHub's OIDC provider issues a JWT with claims like these (shortened):

```json
{
  "iss": "https://token.actions.githubusercontent.com",
  "sub": "repo:TUW-GEO/canvodpy:environment:pypi",
  "aud": "pypi",
  "repository": "TUW-GEO/canvodpy",
  "repository_owner": "TUW-GEO",
  "repository_owner_id": "<numeric owner id>",
  "workflow": "Publish to PyPI",
  "job_workflow_ref": "TUW-GEO/canvodpy/.github/workflows/publish_pypi.yml@refs/tags/v1.0.0",
  "environment": "pypi",
  "ref": "refs/tags/v1.0.0"
}
```

GitHub signs it with its private key. Anyone can verify the signature with
GitHub's public keys at
[`https://token.actions.githubusercontent.com/.well-known/jwks`](https://token.actions.githubusercontent.com/.well-known/jwks).

### 4. Exchange and upload

`uv publish --trusted-publishing always`:

1. Gets the JWT from GitHub's OIDC provider
2. Sends it to PyPI, which verifies it and returns a short-lived API token
3. Uploads the packages with that token

### 5. What PyPI checks

From [PyPI's internals page](https://docs.pypi.org/trusted-publishers/internals/):

- The signature, "to ensure that it's actually coming from the expected
  provider"
- The claims against the registered publishers: repository, workflow file,
  and environment
- The `repository_owner_id` claim, which PyPI always checks for GitHub
  publishers

If the claims match, PyPI issues "a short-lived (15 minute) PyPI API
token," which "is scoped to every project with a matching Trusted
Publisher." If nothing matches, the upload is refused.

---

## Scope of a publisher

Each trusted publisher is bound to:

| Scope | Example | Purpose |
|-------|---------|---------|
| Repository | `TUW-GEO/canvodpy` | Only this repository can publish |
| Workflow | `publish_pypi.yml` | Only this workflow file |
| Environment | `pypi` | Only this environment |
| Package | `canvod-readers` | Only this PyPI project |

So a JWT from another repository, workflow file, or environment gets no
token, and the token a run gets works only for the projects whose
publishers match.

---

## Why several publishers?

The publisher belongs to the project, so every package needs its own:

```
PyPI trusted publishers:
┌──────────────────┬──────────────────┬──────────────────┬──────┐
│ Package          │ Repository       │ Workflow         │ Env  │
├──────────────────┼──────────────────┼──────────────────┼──────┤
│ canvod-readers   │ TUW-GEO/canvodpy │ publish_pypi.yml │ pypi │
│ canvod-auxiliary │ TUW-GEO/canvodpy │ publish_pypi.yml │ pypi │
│ canvod-grids     │ TUW-GEO/canvodpy │ publish_pypi.yml │ pypi │
│ ...              │ ...              │ ...              │ ...  │
└──────────────────┴──────────────────┴──────────────────┴──────┘
```

If you only register `canvodpy`, the workflow can't publish `canvod-readers`.

---

## Deployment environment

```yaml
environment: pypi  # ← Why this matters
```

- **Protection rules:** the environment can require a reviewer's approval
  before the job runs, and limit which branches or tags may deploy to it.
- **History:** the repository lists every deployment to the environment and who
  approved it.
- **OIDC scope:** the JWT names the environment, so a publisher registered
  for environment `pypi` matches no run in any other environment.

---

## Common configuration mistakes

### 1. Mismatched environment name

**Workflow says:**
```yaml
environment: pypi
```

**PyPI registered with:**
```
Environment: py-pi  # ← Note the dash!
```

**Result:** no publisher matches, and the upload is refused.

### 2. Mismatched workflow file

**Workflow filename:**
```
.github/workflows/publish-pypi.yml  # ← Note the dash!
```

**PyPI registered with:**
```
Workflow: publish_pypi.yml  # ← Note the underscore!
```

**Result:** no publisher matches, and the upload is refused.

### 3. Package not registered

You set up a publisher for `canvodpy` but forgot `canvod-readers`.

**Result:** `canvodpy` publishes, `canvod-readers` fails.

---

## Further reading

- [PyPI trusted publishers documentation](https://docs.pypi.org/trusted-publishers/)
- [OpenID Connect](https://openid.net/connect/)
- [GitHub OIDC documentation](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect)
- [GitHub JWKS endpoint](https://token.actions.githubusercontent.com/.well-known/jwks)

---

**Questions?** Open an issue or a discussion.
