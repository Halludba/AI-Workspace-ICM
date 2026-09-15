# Local Compute Capability Protocol

## Purpose
Represent host CPU/GPU/software availability as ephemeral observational evidence, separate from model reasoning, repository authority, mutation governance, and user authorization.

## Discovery
`tools/local_compute.py` may run only fixed, policy-declared read-only probes such as executable lookup, `nvidia-smi` inventory, and FFmpeg encoder listing. A request cannot provide arbitrary shell commands. Discovery output is noncanonical and may become stale immediately after it is produced.

Machine observations such as GPU model, driver, executable paths, or currently installed software are never written into canonical policy as truth. Policy defines probe names and workload requirements only.

## Workload resolution
A named workload resolves to `READY` only when every declared executable and feature requirement is observed available. Missing prerequisites return `BLOCKED` with explicit reasons. `READY` means the host appears technically capable; it does not authorize execution, repository mutation, network access, installation, or resource consumption.

`VIDEO_TRANSCODE_NVENC` demonstrates GPU-backed work without a local ChatGPT model. Remote/model reasoning may orchestrate an authorized host while encoding is performed by local FFmpeg/NVENC. `LOCAL_OLLAMA_WORKER` requires an observed `ollama` executable but does not require ICM itself to run as a local language model.

## Non-guarantees
Executable presence does not prove a workload will succeed. GPU/encoder discovery does not benchmark throughput, guarantee free memory, prove driver correctness, or grant access. Discovery is capability evidence only and must be re-run when current host state matters.
