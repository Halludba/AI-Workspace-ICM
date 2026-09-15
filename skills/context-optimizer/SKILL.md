# Context Optimizer

Load this skill only when token/context growth review is explicitly requested or a deterministic profiler warning fires.

## Purpose
Evaluate whether new repository/context cost is justified by functionality, or whether overlap, poor locality, or avoidable verbosity should be reduced.

## Inputs
- Deterministic token profile and release-over-release deltas.
- The changed files/capability under review.
- Existing routed contracts, tools, skills, or functions that may overlap.

## Review dimensions
- Essentiality: REQUIRED, USEFUL, OPTIONAL.
- Functional gain: SUBSTANTIAL, MODERATE, LIMITED.
- Overlap/redundancy: LOW, MEDIUM, HIGH, or INSUFFICIENT_EVIDENCE.
- Context locality: GOOD, MIXED, POOR.
- Default-context impact versus repository-only growth.

## Rules
Do not recommend removal solely because something is large. Required correctness/security behavior may justify high repository cost. Prefer moving detail out of default context, merging genuine duplicates, or lazy-loading expensive capability context.

If redundancy or value cannot be established from available evidence, return `HUMAN_REVIEW_RECOMMENDED` rather than inventing confidence. This skill is advisory and cannot authorize deletion, mutation, or release.