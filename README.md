# AI Workspace ICM

A host-agnostic, filesystem-first environment for structured AI workflows.

This repository is the clean ICM-native rebuild of the existing AI Workstation architecture. It uses filesystem structure for context routing, scoped contracts for local behavior, durable artifacts for workflow state, semantic models for reasoning, deterministic tools for validation, and Git for canonical history.

## Start here

1. Read `WORKSPACE.md`.
2. Read `CONTEXT.md`.
3. Follow the smallest relevant route.
4. Load only the context declared by that route or stage.

## Architectural boundary

The legacy `Halludba/AI-Workspace` repository remains separate. It is a migration/reference source, not something to copy wholesale into this repository.

The new repository starts at `v0.1.0` because this is a new architecture, not a continuation of the legacy version line.
