# Skills Context

Skills are reusable procedures/capabilities. Load a skill only when selected by the active route/stage and the host actually supports required capabilities. Skills may prescribe procedure but cannot create capabilities or override higher authority. Do not load unrelated skills.

Artifact-producing work uses `skills/registry.json` through `tools/capability_resolver.py`. Classify operation + artifact type first; keywords are fallback evidence, not the primary routing contract. Load only the contexts returned by the resolver.
