# Tools

Deterministic software belongs here.

Use `run_manager.py` as the only normal run lifecycle mutation interface. Its internal `init.py` and `kernel/` modules implement the filesystem-native event journal, reducer, lock, hashing, recovery, and projection mechanics.

Use `run_validator.py` for expensive/full verification boundaries. Normal kernel commands validate their transition and affected delta rather than re-hashing all historical artifacts on every mutation.

Do not edit `RUN.json` or `ATTEMPT.json` as a state-changing operation; they are derived projections. Do not hide semantic governance exclusively inside code: structured policy/core contracts remain inspectable authority and tests remain executable evidence.
