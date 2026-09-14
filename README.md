# AI Workspace ICM

A host-neutral, filesystem-first template for structured AI work.

Current release: **v0.4.0 - generic run/artifact architecture**.

Start here:
1. `WORKSPACE.md` - orientation.
2. `CONTEXT.md` - root router.
3. The selected local `CONTEXT.md` - scoped instructions.
4. Only the references/artifacts declared by that local context or workflow stage.

The base repository is intentionally domain-neutral and designed to be cloned into specialized ICM environments.

`workflows/` stores reusable workflow definitions.
`work/` stores isolated, resumable executions with snapshotted workflow contracts, numbered attempts, validation evidence, and final artifacts.

The model performs semantic reasoning; the filesystem carries context and durable state; deterministic tools validate mechanical invariants; Git is canonical history.
