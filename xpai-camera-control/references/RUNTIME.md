# Native Runtime & Release Reference

Read this file only when maintaining or releasing the skill's native runtime artifacts (the pinned `camera-proto` wheel and `scripts/runtime_artifacts.json`). Normal skill usage never requires it — see [SKILL.md — Installation](../SKILL.md#installation) for the runtime behavior summary.

## How preparation works (details)

The skill ships without native libraries. After acquiring the single-instance lock and starting its lease heartbeat, `mcp_server.py` calls `prepare_runtime.py` before restoring event monitors or starting the MCP transport.

- Preparation uses the reviewed local `scripts/runtime_artifacts.json` shipped with this skill to select a pinned wheel and resource hashes. It installs from the fixed PyPI index only when the package is missing, using the current interpreter's isolated pip, binary-only installation, no dependencies, and a required wheel SHA256.
- After validating installed resource paths and hashes, it stages and atomically replaces only the selected native library and `cacert.pem` in `scripts/toolkit/`.
- An already installed package is checked by version and resource hashes; this does not verify the original wheel archive.
- If preparation fails, the server writes the error to stderr and exits with a nonzero status; it does not start serving tools. Installation output also goes to stderr, never to the JSON-RPC stdout channel.

## Native library loading

The wheel is used only as a native-resource carrier, not as a Python API dependency. This skill retains its own `ctypes` bindings in `scripts/toolkit/camera_proto.py`, including the `2.0.0` ABI check and native string release. Preparation/loading code selects the library per 64-bit interpreter architecture:

| Platform | Library |
|----------|---------|
| Windows x64 | `camera_proto.dll` |
| Linux glibc x64 | `camera_proto.so` |
| macOS Intel / ARM64 | `camera_proto.dylib` |

Linux ARM, musl/Alpine, Windows ARM interpreters, 32-bit interpreters, and unknown combinations are not supported.

## Current artifact boundary

The default manifest still pins the existing production `camera-proto==0.1.0` Windows x64 wheel and its original verified hashes. No four-platform `0.2.0` artifact set has been built or released for this integration. Linux and macOS therefore fail before pip with an explicit missing-verified-artifact message; cross-platform code support is not a claim that those artifacts are ready.

## Maintainer release checklist

To enable a future release, maintainers must review the pipeline's manifest against the final wheels from the same build batch, then ship that complete local manifest with the skill:

- Its `package`, `version`, `environment`, and `platforms` records must agree; supported keys are `win_amd64`, `linux_x86_64`, `macos_x86_64`, and `macos_arm64`.
- Each record pins `wheel_filename`, `wheel_sha256`, `library`, and exactly the native library and `cacert.pem` hashes under `resources`.
- Linux wheels require matching manylinux x64 tags; macOS wheels require matching architecture tags and deployment targets. Preparation checks the host glibc/macOS version against those tags before accepting cached or installed resources; unknown or insufficient versions fail before pip or copying.
- The runtime never downloads a trusted manifest or trusts hashes reported by the installed package. Missing or invalid records fail closed, even if old local files exist. A new manifest's hashes, not the presence of a previous cache, determine readiness.

## Production vs test manifests

- Production manifests use release versions (`x.y.z`).
- Testing requires a separate skill directory and virtual environment with a reviewed local `environment=test` manifest, pinned to an isolated development version (`x.y.z.devN`); changing that field alone does not change a library's compiled environment.
- There is no runtime cloud-domain switch, alternate download endpoint, or automatic environment fallback. Test wheels not published on the fixed PyPI index must be provisioned separately in that isolated environment from the reviewed wheel; preparation does not add a test download source.

## Operational notes

- Initial wheel installation requires network access; startup with local files matching the selected manifest works offline without running pip.
- Preparation does not upgrade or downgrade an existing different package version: use a dedicated virtual environment for this skill if versions conflict.
- Camera tool calls and the library loader never run pip automatically.
- If the first download exceeds the MCP client's startup timeout, run `python scripts/prepare_runtime.py` manually with the same interpreter, then restart the MCP server after preparation succeeds. This optional pre-install step does not access cameras.
