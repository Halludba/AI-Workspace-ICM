# Release Policy

ICM public releases use Semantic Versioning: `MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]`.

## Version meaning
- `PATCH`: backward-compatible fixes, hardening, metadata/governance corrections.
- `MINOR`: backward-compatible functionality or architectural milestones.
- `MAJOR`: stable-contract breaking change; before `1.0.0`, minor releases may still evolve unstable contracts.
- Development iterations are ordinary Git commits; they do not require public version bumps or tags.

## Release boundary
A public release requires the canonical full-regression gate, a release-ready mutation trace, a clean intended diff, and an annotated Git tag matching `v<workspace_version>`.
Published release tags are immutable after adoption of this policy. The malformed `v0.6.0.5` tag was a one-time pre-policy correction and is replaced by `v0.6.1`.

## History and distribution
Git tags are canonical historical release snapshots. Published release tags are retained for compatibility/rollback and are not deleted merely because they are old.
Historical source trees are not duplicated into the checked-out workspace. Normal context uses the current checkout; historical tags are inspected only for explicit history, compatibility, rollback, or migration work.

## Annotated tag notes
Use only relevant sections and omit empty ones: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`, `Breaking`, `Verification`.
The note begins with `ICM v<version> - <title>` and `Previous: v<version>`. `Verification` is mandatory.
