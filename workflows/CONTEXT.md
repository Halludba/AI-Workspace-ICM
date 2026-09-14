# Workflows Context

Reusable multi-stage processes live here. In Step 2, only the workflow root contract is active; specific workflows/stages arrive later. Every future stage must declare Purpose, Inputs, Process, Outputs, Validation, and Handoff. A stage inherits higher authority but not sibling stage context unless explicitly referenced.
