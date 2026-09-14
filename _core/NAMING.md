# Naming Conventions

Filesystem names carry semantic meaning, so naming is part of correctness.

## Directories
Use `lowercase-kebab-case` for ordinary directories.

Examples:
- `agent-development/`
- `reasoning-auditor/`
- `document-production/`

## Architectural contract files
Use uppercase names only for special structural contracts such as:
- `WORKSPACE.md`
- `CONTEXT.md`
- `RUN.md`
- `PROFILE.md`

## Machine-readable state
Use `lowercase_snake_case.json`.

Examples:
- `workspace.json`
- `run_state.json`
- `verification.json`

## Workflow stages
Use zero-padded numeric prefixes plus a short verb/noun:
- `01-discover/`
- `02-design/`
- `03-build/`
- `04-verify/`

## Run folders
Use `YYYY-MM-DD_short-description` unless a workflow defines a stronger identifier.

Example:
- `2026-09-14_reasoning-auditor-validation/`

## Forbidden naming habits
Do not use ambiguous history names such as `final2`, `newnew`, `latest-fixed`, or `temp-old`. Git records history; names should describe current semantic purpose.

## Canonical vs derived names
Generated/derived outputs should be recognizable as such through location or explicit metadata. Do not give a derived file the same authority-signalling name as its canonical source.
