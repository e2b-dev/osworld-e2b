# Source and ownership

The E2B-native implementation was curated from its pre-publication working tree. That source tree
was not itself a Git repository. Only the following implementation families are part of this
repository:

- `template/build.ts`, `template/template.ts`, and the explicitly listed guest files;
- `realkit/*.py`;
- safe scripts and dependency pins under `runner/`;
- tests and task-ID-only validation manifests; and
- package locks and public operator documentation.

The nested `runner/OSWorld` checkout is not a source for repository history. It is fetched by
`runner/setup.sh` from `https://github.com/xlang-ai/OSWorld.git` at the commit recorded in
`upstream.lock.json`. Dotenv files, dependencies, build output, caches, local distributions,
generated evidence, raw trajectories, and experiment probes are outside the public artifact.

`template/files/server/main.py` and `template/files/server/pyxcursor.py` derive from the pinned
OSWorld server package. Their attribution and modifications are recorded in `NOTICE`.
