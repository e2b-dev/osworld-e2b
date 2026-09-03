# Fidelity and validation

## Compatibility boundary

This port reconstructs the OSWorld Linux desktop on Ubuntu 22.04 with GNOME 42, X11, a 1920×1080
framebuffer, the expected productivity applications, AT-SPI, Chrome CDP, VLC HTTP control, and the
OSWorld guest-control API. It is not a bit-for-bit copy of the reference qcow2 image.

The Template pins VS Code 1.91.1 and holds the Chrome package installed during each immutable build.
LibreOffice 7.3.7.2, GIMP 2.10.30, VLC 3.0.16, and VS Code 1.91.1 matched the pinned OSWorld image's
recorded application metadata in the source validation. The reference Chrome version, complete font
inventory, profiles, extensions, accounts, credentials, and proxy state have not been certified as
identical. Tasks that depend on those details can behave differently.

Tasks declaring `proxy=true` are excluded from the default environment-path manifest because this
port does not provision OSWorld's proxy service. `validation/proxy-required.json` retains one such
task as an explicit diagnostic boundary.

## Lifecycle contract

The host relay owns one sandbox at a time. Each OSWorld reset replaces it with a fresh sandbox from
the configured immutable Template. `save_state(name)` creates an E2B runtime snapshot;
`revert_to_snapshot(name)` creates a new sandbox from that snapshot. An unknown name such as
`init_state` creates a fresh sandbox from the immutable Template. Replacement kills the previous
sandbox after the new guest is ready, and shutdown is idempotent.

The guest control service can execute commands. Sandboxes therefore use restricted public ingress,
and the relay injects the per-sandbox traffic token into upstream HTTP and WebSocket requests while
redacting it from public relay state.

## Evidence contract

The fixed manifest covers 24 task IDs across Chrome, GIMP, LibreOffice, multiple applications, OS,
Thunderbird, VLC, and VS Code. For each task, the no-agent harness records reset, setup, screenshot,
accessibility, one scripted action, and evaluator execution. Generated evidence records the exact
OSWorld commit and immutable Template reference.

`PATH_PASS` proves only that the environment path completed. Evaluator score is recorded separately,
and only evaluator output from a real agent run can support a benchmark-success claim.

The source workspace recorded a successful live smoke and two 24/24 environment-path runs on
2026-07-16 against `osworld-gnome:62e8be41-4106-4850-96ea-afc822735b89`. Those generated artifacts
and sandbox identifiers are intentionally not published here. A candidate release must perform a
fresh Template build and live smoke; historical evidence does not satisfy that release gate.
