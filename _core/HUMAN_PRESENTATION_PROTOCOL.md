# Human Presentation & Continuity Protocol

## Purpose
Human-facing ICM communication should expose the smallest useful amount of system state while preserving rigor underneath. Presentation does not change authority.

## Concept Recognition
When the user independently arrives at a well-established computer-science or systems concept and the mapping is strong, briefly name the conventional concept and explain the visible reasoning path that led there.

Use the pattern: `You just rediscovered: <term>. You got there by <short path>.`

Do not force analogies. If several terms fit or the mapping is weak, present them as related concepts rather than claiming one official name. Do not invent standards or imply that a conventional term is universally official when it is not.

The reasoning-path explanation must use visible user observations and conclusions, not private model reasoning.

## Continuity footer
For substantial ICM/system work, end with a compact continuity block when useful:
- `Next optimal step:` the active/next accepted planner task, if one exists.
- Otherwise, a clearly labeled candidate suggestion may be shown, but it is not executable work.
- `Unopposed / unresolved ideas:` a short title-only summary of unresolved suggestions when present.

Do not repeat full suggestion explanations every turn. Do not add the footer to trivial or unrelated answers merely because ICM exists.

## Truth hierarchy
Live Git/run state is canonical truth. The planner carries accepted execution intent. The suggestion queue carries unresolved ideas. Current model context is warm working memory only.

## Authority
SIMPLE/STANDARD/TECHNICAL density, concept callouts, next-step summaries, and suggestion summaries change communication only. They never grant execution or mutation authority.
## Mechanical continuity enforcement
For a substantial ICM response, when the active planner exposes an executable next action, the response contract requires a non-empty `Next optimal step` footer. `tools/continuity_presenter.py validate-response` enforces this mechanically. Candidate suggestions remain non-executable and presentation never changes rigor or authority.
