# Suggestion Continuity Protocol

## Purpose
Useful suggestions may outlive the conversation turn where they were proposed. ICM preserves them cheaply without treating silence, topic change, or mere storage as approval.

## State model
`PROPOSED -> UNOPPOSED | ACCEPTED | REJECTED | SUPERSEDED | EXPIRED`

`UNOPPOSED` means the user did not reject the idea and conversation may have moved on. It is not approval and carries no execution authority.

## Interaction rules
1. Topic change is neutral. It never automatically rejects or accepts a suggestion.
2. Silence is neutral. It never grants execution, mutation, release, purchase, send, or other action authority.
3. Only `ACCEPTED` suggestions are eligible to become planner tasks. Acceptance still does not bypass plan sufficiency, role, mutation, or release governance.
4. The suggestion queue is per-agent, Git-ignored, noncanonical, and disposable. Git remains implemented truth; the session planner remains accepted execution intent.
5. Compact summaries may expose unresolved titles/statuses without loading full suggestion bodies.
6. Exact approval phrases have bounded scopes: `go ahead` = current primary suggestion; `go ahead with all` = current presented bundle; `go ahead with all pending suggestions` = all unresolved pending suggestions. Other natural language must be semantically resolved before the deterministic scope is applied.
7. `all` never silently means historical suggestions outside the stated/current scope.
8. Revalidate compatibility before promoting an old suggestion whose reviewed revision no longer matches current canonical state.
9. When the current user explicitly authorizes implementation conditional only on there being no material counter-suggestion or blocker, completing that review with none resolves the condition and execution may continue under normal mutation governance without asking for another confirmation. The review result does not create authority; the user instruction already supplied it.

## Authority
Suggestion storage, approval-scope resolution, and promotion eligibility are advisory/continuity mechanics. They grant no repository mutation authority by themselves.