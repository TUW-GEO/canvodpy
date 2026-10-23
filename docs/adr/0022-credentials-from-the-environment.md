# canvodpy stores no secrets; credentials come from the environment

*Proposed 2026-10-20 (canvodpy-extensions #78).*

canvodpy reads data that can need a credential: naming recipes in a
private GitHub repository (canvodpy-extensions #78), stores on S3, and
later stores on commercial S3 providers. A secret that sits in a
settings file, a `.env` file or a store's metadata is copied with it,
and stays in its history.

**canvodpy never stores a secret.** No settings field holds one, the
settings loader reads no `.env` or secrets file, and no secret is
written to a store, a log, a message or the run history.

**Each service takes its provider's standard environment variables.**
canvodpy adds no variables of its own for secrets:

| Service | Variables |
|---|---|
| Naming recipes on GitHub | `GH_TOKEN`, then `GITHUB_TOKEN` |
| Stores on S3 | The AWS variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_PROFILE`) or the shared AWS files (`~/.aws/credentials`, `~/.aws/config`) |

**Where the secret lives is the user's choice.** The system keychain, a
password manager that starts a program with the secret in its
environment (for example `op run -- canvodpy run ...`, `bws run`), or
the secrets store of a scheduler (Airflow, Windmill). canvodpy works
the same with each, on every operating system.

**A secret goes only where it belongs.** A recipe token is sent only to
`raw.githubusercontent.com`, never to the target of a redirect. A
recipe URL with a user name, password, query or fragment is refused, so
no secret reaches the store's metadata through the URL.

## Considered options

- **A variable of our own (`CANVOD_RECIPE_TOKEN`).** One more secret to
  manage, next to the `GH_TOKEN` that `gh` and CI already use.
- **A `.env` file or a secrets file read by the settings loader.** The
  secret then sits in a file next to the settings, and is copied and
  committed with them.
- **canvodpy reads the keychain or a password manager itself.** Each
  tool and operating system needs its own code, and a headless server
  usually runs no keychain. Starting canvodpy with the secret in its
  environment works with all of them.
- **Asking for the secret at run time.** Scheduled runs (Airflow,
  Windmill) have no one to ask.

## Consequences

- Public recipes and stores that need no credential work without any
  setup.
- The NASA Earthdata email
  (`CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL`) is no
  secret and stays a setting.
- A credential for a new service follows this ADR: its provider's
  standard variables, or a new ADR.
