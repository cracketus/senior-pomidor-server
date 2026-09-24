# Senior Pomidor operator TUI

Issue: #207

The operator TUI is a read-only, SSH-friendly view over the versioned `senior-pomidor.operator.v1` API. It reuses the canonical `pomidorctl` configuration and `OperatorClient`; it does not query PostgreSQL/internal tables and has no actuator/control mutation path.

## Install

```bash
python -m pip install -e ".[tui]"
```

Development installs (`.[dev]`) include Textual as well. Run this command only from a source checkout.
The source-free runtime bundle is not a pip project; the API image installs the base package without
Textual. Install the operator client on a workstation/SSH host in a separate virtual environment, pinned
to the accepted release tag or full SHA. Do not install packages into a running production container.

## Run

```bash
pomidorctl tui
pomidorctl tui --server-url http://127.0.0.1:8000
pomidorctl tui --refresh-seconds 60
```

The same `POMIDORCTL_SERVER_URL`, `POMIDORCTL_TIMEOUT_SECONDS`, `POMIDORCTL_TOKEN_FILE`, and `POMIDORCTL_TOKEN` configuration rules used by the read-only CLI apply to the TUI. Credentials are never rendered.

For sanitized screenshots, recordings, talks, and contributor development:

```bash
pomidorctl tui --demo
```

## Navigation

| Key | View/action |
| --- | --- |
| `1` | Overview |
| `2` | Plant / pod |
| `3` | Edge |
| `4` | Decisions |
| `5` | Events / anomalies |
| `6` | Camera metadata |
| `r` | Refresh |
| `q` | Quit |

Mouse interaction is not required.

## Failure semantics

The server remains the owner of operator status/freshness/availability/completeness semantics. Transport state is represented separately:

- no successful payload -> `DISCONNECTED`;
- failed refresh after a successful read -> explicitly marked `STALE LAST-KNOWN DATA`;
- API failure never becomes apparent `OK`;
- contract validation is owned by the shared `pomidorctl` client;
- fields not exposed by the operator contract remain `UNAVAILABLE`/`NOT_IMPLEMENTED` rather than inferred.

In the v0.3.1 operator fix, a refresh already in flight is allowed to complete; timer ticks and repeated
`r` presses do not cancel it or start overlapping request batches. Composite views show transport
warnings for their dependent sections independently.

The synchronous shared client runs via `asyncio.to_thread`, keeping Textual keyboard interaction responsive while avoiding a second HTTP/contract implementation.

Terminal image rendering is intentionally not a v1 dependency; Camera displays metadata only.
