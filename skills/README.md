# Skills

Skills are reusable procedures or capability packages that workflows/stages may load when needed.

Skills are not workflow state and should not silently become globally active.

A skill should state what it does, required inputs/capabilities, outputs, and deterministic/semantic boundaries when materialized in a later step.
Current routed skills:
- `context-optimizer` - advisory redundancy/value/locality review loaded only on explicit request or token-growth warning.
- `pdf-styler` - shared PDF presentation capability selected for CREATE/EDIT/STYLE + PDF; excluded for ordinary PDF reading/analysis.
