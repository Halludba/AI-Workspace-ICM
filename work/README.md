# Work

Concrete workflow executions live here.

Each run is isolated under `work/<run-id>/` and records its own inputs, workflow-definition snapshot, current pointer, stage attempts, validation evidence, and final artifacts.

The reusable workflow remains under `workflows/`; the run records one execution of it.

Use `tools/create_run.py` to create a run from an `ACTIVE` workflow and `tools/run_validator.py` to validate run integrity.

Do not place reusable global rules here. Run artifacts become canonical/reference state only through an explicit governed promotion.

`work/_template/` is structural documentation only and is never executable.
