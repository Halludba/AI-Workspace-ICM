# Workflows

This root contains reusable workflow definitions, not execution history.

Each executable workflow has:
- `CONTEXT.md`
- `WORKFLOW.json`
- ordered stage directories

Each stage has:
- `CONTEXT.md`
- `STAGE.json`

The reserved `_template/` workflow is non-executable and exists only to scaffold new workflows in this repository or future clones.

Run-specific artifacts belong under `work/`, never inside `workflows/`.
