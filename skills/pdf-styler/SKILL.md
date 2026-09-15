# PDF Styler

Load this skill only when the capability resolver selects `pdf-styler` or the user explicitly requests it.

## Purpose
Apply reusable presentation styling when creating, materially editing, or restyling a PDF. Content semantics remain owned by the requesting workflow/user.

## Selection contract
- Match operations: `CREATE`, `EDIT`, `STYLE`.
- Match artifact type: `PDF`.
- Do not load for ordinary PDF reading, summarization, extraction, or analysis.
- Explicit user style choice outranks document/project/default style bindings.

## Priority
1. Semantic correctness and explicit user content.
2. Readability/accessibility.
3. Layout integrity.
4. Style fidelity.
5. Decorative preference.

## Execution
Resolve the style from `manifest.json` / `pdf_styles/`, validate it against `pdf_style_schema.json`, then use an available PDF renderer. The bundled ReportLab adapter is `tools/pdf_styler.py`; if its declared dependencies are unavailable, do not fabricate execution—use another authorized renderer while preserving the style contract or report the missing capability.

## Context economy
The manifest and this file are selected context. Renderer source, schema, and presets are data/tooling and remain unloaded unless execution or inspection requires them.
