# Contributors develop with agents through one shared workflow: the mattpocock-skills plugin

Most contributors are scientists who develop with coding agents. A fixed
workflow raises the quality of what they build: an interview before any
code, recorded decisions and terms, tests first, and a review against the
coding standards and the request. canVODpy adopts the open source
[mattpocock/skills](https://github.com/mattpocock/skills) (MIT) for this.
`.claude/settings.json` declares its author's GitHub marketplace and
enables the plugin; `just agent-skills` installs or updates it. Its
configuration for canVODpy lives in `docs/agents/`, the decisions in
`docs/adr/`, the terms in `GLOSSARY.md`, the rules it reviews against in
`CODING_STANDARDS.md`.

## Considered options

- Copying the skills into the repository would pin them and allow
  editing, but every contributor would carry a fork that no longer
  follows its author's fixes. canVODpy-specific steps stay in canVODpy's
  own files and skills instead.
- The official Claude marketplace lists the same plugin, but lags behind
  its releases (in October 2026 it served 1.2.3, which still named the
  glossary CONTEXT.md).
