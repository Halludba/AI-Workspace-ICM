# Profiles Context

Profiles are reusable behavior/context specializations, not independent authorities and not host capabilities. `config/role_policy.json` selects `icm-system-architect` as the default ICM role; other profiles are loaded only when the role policy, an active workflow/stage/route, or the current user instruction selects them. Do not load sibling profiles automatically.

Selected profiles live at `profiles/<profile-id>/PROFILE.md`. Role selection and repository inspection do not grant mutation authority. Mutation-capable profiles still require current user authorization and must remain inside their declared mutation envelope.

The System Architect may inspect canonical repository evidence without escalating merely because source inspection is required. Escalate to Runtime Architect only for live implementation/runtime/release work, or to the scoped workflow/profile/skill author when that domain is the actual mutation target.
