# Tests

Machine-verifiable invariants for the reusable ICM base live here.

Current coverage includes context routing, workflow/stage contracts, journal-backed run creation, definition sealing, explicit attempt lifecycle, retry semantics, artifact confinement/hashing, append-only validation history, operation-id idempotency/conflicts, projection recovery, checkpoint fallback, journal sequence corruption, event ceilings, lock ownership/recovery, malformed JSON structures, fenced-Markdown parsing, symlink escapes, platform-specific process identity, randomized legal state-machine sequences, universal BIOS response declarations, two-axis mutation governance with commit-readiness/target-linkage checks, Git-aware verification blast-radius classification, and privacy-safe append-only decision records with supersession.

Passing tests are evidence for the implemented contract, not proof of arbitrary semantic correctness. Reachability tests establish graph reachability only; they do not prove that a permitted looping execution will terminate.

For release closure run the complete suite, both validators, Python compilation, stale-reference checks, and `git diff --check`.
