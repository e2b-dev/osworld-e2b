# Full OSWorld 1.0 Support and Docker-Parity Design

## Purpose

This repository runs the complete official OSWorld 1.0 suite on native E2B sandboxes, preserves
the upstream task and evaluator behavior, records every scheduled task attempt, and produces a
score directly comparable with a public Docker run of the same model. The sandbox is the virtual
machine; the implementation does not run QEMU or another hypervisor inside E2B.

The integration has two immutable upstream profiles because “current OSWorld support” and
“historical result reproduction” require different source snapshots:

- `current-v1` pins `xlang-ai/OSWorld` commit
  `fc31a9049664292fcb35d6e501ee1dc839f2cf6d`. It is the default support profile and contains all
  369 tasks in `evaluation_examples/test_all.json`, including the eight authenticated Google
  Drive tasks. Its public no-Google-Drive lane contains 361 tasks.
- `ui-mopd-qwen3vl-docker` pins commit
  `fe8c78e15a1149e82d54137e9ffef18aee710ed7` and the public UI-MOPD evidence at Hugging Face
  dataset commit `a518b8776c172c9456f85b3fa5ef451d326a7969`. The OSWorld commit is a documented inference:
  the run occurred on June 22, 2026, while that commit was official main, but the evidence did not
  record the source SHA. Results from this profile are therefore aggregate-comparable evidence,
  not strict source-proven task-level parity.

Every profile records the repository URL, commit, suite files, runner, task-file SHA-256 values,
and evaluator-tree digest. Setup verifies those identities before applying the E2B boundary patch.
No mutable branch or tag is accepted as a runnable profile.

## Architecture

Each OSWorld `DesktopEnv` owns one E2B provider instance. The provider starts a dedicated localhost
relay subprocess with an operating-system-assigned port bundle, waits for its control endpoint,
and obtains the guest-control, Chrome DevTools Protocol, and VLC endpoints from that relay. The
relay owns exactly one E2B sandbox and its traffic token. Stopping the provider stops the relay and
kills or records the cleanup failure for every sandbox it created.

This moves parallelism to the correct boundary. Upstream OSWorld workers can construct independent
`DesktopEnv` objects without sharing relay state, ports, sandbox objects, logs, or result paths.
The default campaign concurrency is eight and is configurable up to the lower of the validation
contract's sandbox cap and the operator's requested value. Sandbox concurrency and model-serving
endpoint concurrency remain separate limits.

The campaign coordinator runs one upstream task per child process. It creates a one-task manifest,
an isolated result directory, an isolated upstream log directory, and an isolated relay event log
for each attempt. Running only one task in each child makes dequeue, timeout, process death, and
cleanup outcomes attributable to one task while retaining the authoritative upstream runner,
agent, task setup, and evaluator. The coordinator schedules children concurrently and can resume a
run by scheduling only task-attempt pairs without a valid terminal record.

The E2B patch remains a generated, deterministic boundary change. It adds the provider factory,
recognizes E2B as a fresh cloud environment, forces a fresh sandbox on resets, passes dynamic
relay endpoints, and exposes runner arguments needed by the pinned Qwen agent. It does not alter
task JSON, setup steps, getters, metrics, or evaluator code.

## Full-suite capabilities

The current profile exposes three explicit suites:

- `all`: all 369 official tasks;
- `nogdrive`: the 361-task public suite used by comparable public runs; and
- `gdrive`: the eight-task difference between the two official manifests.

Proxy-required tasks are not filtered. OSWorld's own `proxy=true` handling runs unchanged and E2B
provides normal outbound network access. The operator supplies a proxy configuration through
`PROXY_CONFIG_FILE`; its contents and credentials are never copied into committed files, command
arguments, run manifests, or retained logs. Preflight rejects placeholder proxy credentials when a
selected task requires them.

Google Drive credentials are supplied through OSWorld's `--vm_secret_mount` interface. The E2B
provider uploads each requested file through the authenticated guest-control channel on every new
sandbox and applies restrictive guest permissions. Run records retain only the guest destination,
source-file SHA-256, and a redacted source label. They never retain the host path or secret bytes.
The `all` and `gdrive` suites fail preflight when their required credential mounts are absent.

## Result and recovery contract

Each campaign creates an ignored `results/runs/<run-id>/` bundle containing:

- `run.json`: immutable profile, suite, template `name:build_id`, runner, model settings, caps,
  task inventory digest, start and finish state, and sanitized host dependency versions;
- `attempts.jsonl`: append-only `PLANNED`, `STARTED`, and terminal events for every logical
  task-attempt pair;
- `aggregate.json`: continuously regenerated complete, valid, invalid, missing, score, resource,
  and cleanup accounting;
- `attempts/<domain>/<task-id>/<attempt>/`: captured stdout, stderr, upstream screenshots,
  trajectory, runtime log, recording, result, relay lifecycle events, and artifact checksums.

A task attempt is `valid` only when the child exits normally, the authoritative upstream evaluator
produces a finite reward, the expected task/profile identities match, and relay evidence records
successful sandbox cleanup. Timeouts, malformed or absent results, source drift, process failure,
and failed cleanup are separate invalid reasons and never silently become zero-reward task results.
Retries apply only to invalid attempts, are bounded by the validation contract, and keep all prior
attempt evidence. Agent-scored zero is a valid result.

On interruption, the coordinator terminates children, asks every relay to stop, writes terminal
`interrupted` records where possible, and leaves any unclosed `STARTED` event visible as missing.
Resume never deletes incomplete evidence. It appends a new attempt for each eligible invalid or
missing pair.

Raw bundles stay ignored because they can be large and may contain sensitive visual state. A
sanitized evidence summary containing immutable identities, aggregate counts, reward, resource
summary, and bundle checksums is suitable for publication.

## Qwen Docker comparison

The comparison model is
`UI-MOPD/Qwen3-VL-8B-Thinking-UI-MOPD-Student` at Hugging Face commit
`3e6acbe78847870fc645786bfaf55c64bff84903`. The parity profile uses screenshot observations at
1920×1080, pyautogui actions, relative coordinates, 50 maximum steps, three-turn trajectory
history, temperature 0, top-p 0.9, and 2,048 maximum output tokens. It targets operator-supplied
OpenAI-compatible endpoints, normally a pinned vLLM or SGLang deployment of those weights.

The public Docker evidence contains 359 evaluator results for the 361-task no-Google-Drive suite.
Its fractional reward sum is `132.79220946530714`. For the public comparison only, the two absent
tasks are counted as zero, yielding `0.36784545558256826` over the declared 361-task denominator.
The README's `126/359` value is a strict binary-success count and is reported as secondary context,
not as the OSWorld fractional-reward score.

The E2B promotion campaign requires 361 valid E2B task results. It reports the E2B fractional mean,
the difference from `0.36784545558256826`, the 359-task common-set comparison, and the two public
reference omissions. The acceptance band is an absolute difference no greater than 0.03. Because
the public evidence does not authenticate its OSWorld source commit and lacks two outcomes, passing
this gate establishes comparable aggregate parity, not strict task-level equivalence.

## Validation and cost gates

Offline validation covers profile schema and checksums, deterministic patching against both pins,
dynamic port isolation, provider-owned relay lifecycle, secret redaction, result-state transitions,
resume behavior, aggregation, and contract validation. A no-model fake runner exercises parallel
success, zero reward, timeout, crash, malformed result, interruption, and cleanup failure.

Live validation follows the benchmark rewrite ladder: fresh-sandbox readiness; representative
proxy-free, proxy-required, and credential-injection environment paths; lifecycle probes; positive
and negative evaluator controls; a representative authoritative agent run; then resource
profiling. Every live artifact records the immutable E2B Template reference.

No paid sandbox or model campaign starts merely because credentials are present. The final
`validation-contract.json` must pin the profile, 361-task inventory, template build ID, runner,
model commit and endpoints, settings, retry and timeout rules, the public evidence, the 0.03 band,
an E2B sandbox concurrency cap, and an independent model-request upper bound. The operator must
explicitly authorize that validated contract immediately before billable execution.
