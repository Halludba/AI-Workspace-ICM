# Work

Concrete workflow executions live here. Each real run is isolated under its own run directory.

Preferred CLI:
- POSIX/macOS/Linux: `./icm run init <workflow-id> <run-id>`
- Windows: `icm.cmd run init <workflow-id> <run-id>`

`python tools/run_manager.py ...` remains the direct Python entrypoint for development/testing, but `run_manager.py` is the same single lifecycle authority in either case.

Canonical execution history lives under each run's immutable `journal/`. `RUN.json` and `ATTEMPT.json` are derived projections for fast orientation and are regenerated from the journal when drift is detected.

The reserved `_template/` directory is non-executable and exists only as a structural reference.
