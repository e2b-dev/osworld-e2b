# Source and ownership

This repository owns the E2B provider boundary, Template recipe, relay, campaign accounting,
validation contracts, generated task inventories, tests, and operator documentation. It does not
vendor OSWorld.

Official upstream source is fetched from `https://github.com/xlang-ai/OSWorld.git` into the ignored
`runner/OSWorld/` directory. `validation/profiles.json` is authoritative for runnable source:

- `current-v1` pins verified official commit
  `fc31a9049664292fcb35d6e501ee1dc839f2cf6d`;
- `ui-mopd-qwen3vl-docker` pins
  `fe8c78e15a1149e82d54137e9ffef18aee710ed7`, inferred as the official main revision corresponding
  to the public run date because that result did not record an OSWorld SHA.

Each committed inventory is generated directly from the selected checkout. It records the source
commit, official suite manifest, task-file SHA-256 values, proxy flags, evaluator-tree digest, and
whole-inventory digest. Setup verifies these bytes before applying a deterministic patch limited to
the E2B provider factory, fresh-reset behavior, supported upstream runners, and generated adapter
files. Task definitions and evaluator implementations are never rewritten.

`upstream.lock.json` and `template/inputs.lock.json` pin the current Template input. Historical
comparison identity and the public result artifact are separately pinned in
`validation/profiles.json` and `validation/reference/ui-mopd-qwen3vl-docker.json`.

The public implementation families are `template/`, `realkit/`, safe scripts and dependency pins
under `runner/`, generated validation metadata, tests, package locks, and documentation. Dotenv
files, dependencies, build output, caches, local distributions, fetched upstream checkouts, raw
trajectories, credentials, and generated campaign bundles are outside the public artifact.

`template/files/server/main.py` and `template/files/server/pyxcursor.py` derive from the pinned
OSWorld server package. Their attribution and modifications are recorded in `NOTICE`.
