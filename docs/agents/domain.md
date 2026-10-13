# Domain docs

How the engineering skills should consume this repository's domain documentation when exploring the codebase.

canVODpy is a **single-context** repository: its packages share one domain (GNSS-T, sites, files, stores), so there is one glossary and one set of decisions at the root, not one per package.

## Before exploring, read these

- **`GLOSSARY.md`** at the repository root: the project's words.
- **`docs/adr/`**: read the decisions about the area you're about to work in (`docs/adr/index.md` lists them).
- **`CODING_STANDARDS.md`**: the rules every change follows.
- The **`AGENTS.md`** of every package you change: where things live, invariants, tests.

## File structure

```
/
├── GLOSSARY.md
├── CODING_STANDARDS.md
├── AGENTS.md
├── docs/adr/
│   ├── index.md
│   ├── 0001-versioned-stores.md
│   └── ...
└── packages/<package>/AGENTS.md
```

A new ADR takes the next free number and gets a row in `docs/adr/index.md` and an entry under `Decisions` in the nav of `zensical.toml`; the docs site shows them under Development > Decisions.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/mattpocock-skills:domain-modeling`).

## Flag conflicts with an ADR

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (provenance in log books), but worth reopening because…_
