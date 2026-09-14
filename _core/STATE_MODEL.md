# State Model

The workspace separates four state classes.

## 1. Canonical state
Intentional persistent system configuration and contracts: core rules, active profiles, workflow definitions, and approved machine configuration.

## 2. Reference state
Stable reusable knowledge that informs work but is not execution state. Lives primarily under `references/`.

## 3. Run state
State for one concrete execution: inputs, stage outputs, approvals, checkpoints, verification evidence, and final artifacts. Lives under `work/`.

## 4. Derived state
Regenerable indexes, caches, summaries, renders, manifests, and exports. Derived state must identify its source inputs and must not silently become canonical.

## Promotion rule
A run artifact becomes canonical/reference state only through an explicit governed decision. Copying or generating a file does not automatically promote its authority.

## Freshness rule
When derived or conversational state conflicts with canonical state, canonical state wins. When canonical state conflicts with a new explicit user directive, the directive wins and canonical state should be updated if the change persists.

## Persistence rule
If a fact is important to future execution, store it in an appropriate durable file rather than relying solely on conversation memory.
