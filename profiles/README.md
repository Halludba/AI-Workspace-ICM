# Profiles

Profiles are reusable behavior/context specializations for a capable host model.

A profile may shape role, priorities, review criteria, output contracts, and local behavior. A profile does not create capabilities the host does not possess and does not become an independent authority.

Profiles should remain local, inspectable, and composable rather than duplicating shared logic under multiple labels.
## Profile contract
Each installed profile lives at `profiles/<profile-id>/PROFILE.md` and uses these sections in order: Identity, Purpose, Activation, Operating Priorities, Required Behaviors, Output Discipline, Authority Boundary, and Non-Goals. Profile IDs are lowercase kebab-case. Profiles are opt-in selected context; they are never auto-loaded as resident agents.

## Installed reusable specialists
- `reasoning-auditor` -> epistemic/evidence/decision-quality review without private reasoning capture.
- `prompt-architect` -> prompt and instruction architecture, hierarchy, efficiency, and injection hardening.
- `project-scout` -> evidence-aware AI project/opportunity discovery and bounded experiment selection.
