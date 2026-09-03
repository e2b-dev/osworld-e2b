# Fidelity and validation

## Compatibility boundary

The port reconstructs OSWorld's Linux desktop on Ubuntu 22.04 with GNOME 42, X11, a 1920×1080
framebuffer, the expected productivity applications, AT-SPI, Chrome CDP, VLC HTTP control, and the
OSWorld guest-control API. E2B replaces the VM provider boundary; upstream task JSON, setup steps,
agent actions, getters, metrics, and evaluators remain unchanged.

This is not a bit-for-bit copy of the Docker or qcow2 environments. The Template pins VS Code
1.91.1 and records the Chrome package installed during each immutable build. LibreOffice 7.3.7.2,
GIMP 2.10.30, VLC 3.0.16, and VS Code 1.91.1 matched the upstream image metadata during source
validation. Exact Chrome binaries, fonts, profiles, extensions, cached state, accounts, proxy
infrastructure, and external services can still differ and can affect scores.

## Suite boundary

The default `current-v1` profile pins official OSWorld commit
`fc31a9049664292fcb35d6e501ee1dc839f2cf6d` and generated inventories for:

- `all`: 369 tasks, including 56 tasks marked `proxy=true`;
- `nogdrive`: 361 tasks, including 49 tasks marked `proxy=true`;
- `gdrive`: eight tasks, seven of which are marked `proxy=true`.

Proxy tasks are supported rather than filtered. They require a real runtime `PROXY_CONFIG_FILE`;
preflight rejects absent, malformed, or placeholder configurations. The `all` and `gdrive` lanes
also require one or more `local_path:/opt/osworld/secrets/...` mounts. Secret bytes and host paths
are not retained; evidence records only the guest path, source filename, and source SHA-256.

The 24-task `validation/manifest.json` remains a fast cross-application smoke lane. It is not the
support boundary and must not be reported as full-suite coverage.

## Build and lifecycle boundary

The build recipe uses a platform-specific Ubuntu image digest, a pinned OSWorld commit, locked npm
dependencies, and a hash-locked transitive guest Python environment. Content-derived naming covers
Template sources, guest files, resource allocation, and lock files. Rolling apt and Chrome inputs
mean the resulting filesystem is not asserted byte-reproducible. The immutable E2B
`name:build_id`, not the recipe name alone, is the runnable identity.

Every OSWorld environment owns one relay, dynamically allocated control/server/CDP/VLC ports, and
one E2B sandbox. A reset creates a fresh sandbox. A named `save_state` creates an E2B runtime
snapshot; reverting creates a new sandbox from that snapshot. Unknown names, including the normal
`init_state`, create a fresh sandbox from the immutable Template. Shutdown always attempts relay
and sandbox cleanup and records failure separately.

The guest control service can execute commands. Public ingress is restricted, and the relay injects
the per-sandbox traffic token into upstream HTTP and WebSocket requests without exposing it to
OSWorld or retained state.

## Result evidence boundary

The campaign ledger is append-only and crash-visible. A task becomes valid only after the
authoritative runner exits normally, exactly one finite evaluator result is found, task identity is
unchanged, and relay evidence reports successful cleanup. Agent-scored zero is valid. Timeout,
runner exit, missing result, malformed result, identity drift, cleanup failure, and interruption are
invalid classes and never become synthetic zeros. Bounded retries append new attempts and retain
all earlier evidence.

`PATH_PASS` from the no-agent harness proves reset, setup, observation, action, and evaluator
transport only. It is not an agent task pass. A benchmark score requires a complete authoritative
agent campaign.

## Docker parity boundary

The public comparison is UI-MOPD's Qwen3-VL Docker result at dataset commit
`a518b8776c172c9456f85b3fa5ef451d326a7969`, using model commit
`3e6acbe78847870fc645786bfaf55c64bff84903`. The run evidence contains 359 of the declared 361
no-Google-Drive outcomes. Its fractional sum is `132.79220946530714`; treating the two public
omissions as zero gives `0.36784545558256826` over the declared denominator. The published
`126/359` figure is a binary-success statistic and is not substituted for the fractional OSWorld
score.

The E2B lane requires all 361 valid results, reports both full-denominator and 359-task common-set
scores, and accepts an absolute aggregate difference no greater than `0.03`. The historical
OSWorld commit `fe8c78e15a1149e82d54137e9ffef18aee710ed7` is inferred from the June 22, 2026 run date
and official main history because the public result did not record a source SHA. Passing therefore
supports aggregate provider parity; it cannot prove strict source-authenticated task-level or
filesystem parity.

No paid run starts from credentials alone. Execution additionally requires a reviewed contract
with a final immutable template, exact inventory and model identities, explicit sandbox and model
request caps, resolved endpoint labels, and `execution_authorized: true`.
