# Profiles Context

Profiles are reusable behavior/context specializations, not independent authorities and not host capabilities. Load one only when the active route/workflow declares it relevant. Profile instructions remain below core and active workflow/stage authority. Do not load sibling profiles automatically.
Selected profiles live at `profiles/<profile-id>/PROFILE.md`. Load only the exact profile IDs explicitly named by the current workflow/stage/route or user instruction. Do not infer adjacent profiles from topical similarity.
