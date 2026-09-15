# Profiles

Profiles are reusable behavior/context specializations for a capable host model. A profile may shape role, priorities, review criteria, output contracts, and local behavior; it does not create host capabilities or independent authority.

## Profile contract
Each installed profile lives at `profiles/<profile-id>/PROFILE.md` and uses these sections in order: Identity, Purpose, Activation, Operating Priorities, Required Behaviors, Output Discipline, Authority Boundary, and Non-Goals. Profile IDs are lowercase kebab-case.

`icm-system-architect` is selected by the role policy as the default ICM role. Other profiles are selectively routed; siblings are not resident or auto-loaded. Role activation does not imply mutation authorization.

## Installed roles and specialists
- `icm-system-architect` -> default read-only architecture/research/review/planning coordinator.
- `icm-runtime-architect` -> authorized runtime/kernel/tooling implementation, live execution, testing, and release specialist.
- `workflow-architect` -> scoped workflow authoring under `workflows/**`.
- `profile-architect` -> scoped profile authoring under `profiles/**`.
- `skill-architect` -> scoped skill/capability authoring under `skills/**`.
- `reasoning-auditor` -> epistemic/evidence/decision-quality review without private reasoning capture.
- `prompt-architect` -> prompt and instruction architecture, hierarchy, efficiency, and injection hardening.
- `project-scout` -> evidence-aware AI project/opportunity discovery and bounded experiment selection.
