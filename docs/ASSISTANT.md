# Senior Pomidor Conversational Assistant

Senior Pomidor includes a provider-neutral, read-only assistant backend grounded in stored plant data. The initial provider, `planttalk_openai`, creates OpenAI Realtime WebRTC sessions for text and audio clients.

The backend API is available now. A bundled browser conversation UI is not part of issues #101 or #102; it is planned separately in #103. Creating a session returns connection credentials and does not itself return an assistant answer.

## What The Assistant Can Read

Every session is bound to one validated device/node. The server builds a bounded context from that node only:

- latest stored canonical state
- recent telemetry history
- active anomalies
- latest sensor health
- recent photo metadata

The provider-neutral tools are `get_current_state`, `get_recent_history`, `get_active_anomalies`, `get_sensor_health`, and `get_recent_photos`. They cannot modify stored data or select another node. Photo metadata does not contain storage paths, and image bytes are not sent through these tools.

The selected, bounded plant context is included in the Realtime session configuration sent to OpenAI. The permanent OpenAI API key stays on the Senior Pomidor server; the client receives only a short-lived Realtime client secret. Conversation transcripts are not stored by Senior Pomidor in PostgreSQL, files, logs, metrics, or the in-memory session registry. Review OpenAI's applicable data controls separately before enabling the provider.

## Prerequisites

- The API service is running on a trusted LAN.
- The selected node already appears in `GET /api/v1/devices` and has stored data.
- The OpenAI account associated with the configured API key can use the configured Realtime model.
- The host can make outbound HTTPS requests to `api.openai.com`.

Public internet exposure is unsupported. Use a VPN or an authenticated TLS reverse proxy if access is needed outside the trusted LAN.

## Configure The Provider

Copy the environment template if the deployment does not already have a `.env` file:

```powershell
Copy-Item .env.example .env
```

Set at least these values in `.env`:

```dotenv
ASSISTANT_PROVIDER=planttalk_openai
OPENAI_API_KEY=<server-side-openai-api-key>
ASSISTANT_BEARER_TOKEN=<strong-random-lan-token>
```

`ASSISTANT_BEARER_TOKEN` is optional for compatibility with trusted-LAN defaults, but it is strongly recommended. It is independent of telemetry and photo upload tokens.

Optional settings and defaults:

| Setting | Default | Meaning |
| --- | --- | --- |
| `ASSISTANT_REALTIME_MODEL` | `gpt-realtime` | Realtime model used for new sessions. |
| `ASSISTANT_REALTIME_VOICE` | `marin` | Audio voice configured for the session. |
| `ASSISTANT_SESSION_TTL_SECONDS` | `600` | Local session and client-secret lifetime; valid range is 10–7200 seconds. |
| `ASSISTANT_PROVIDER_TIMEOUT_SECONDS` | `15` | Timeout while the server requests a client secret. |
| `ASSISTANT_RATE_LIMIT_REQUESTS` | `60` | Requests allowed per client and assistant endpoint in one window. |
| `ASSISTANT_RATE_LIMIT_WINDOW_SECONDS` | `60` | Fixed rate-limit window duration. |

Apply the configuration by recreating the API service:

```powershell
docker compose up -d --build api
docker compose logs --tail 100 api
```

The rest of the stack remains operational when the assistant is disabled or lacks provider credentials.

## Verify Availability

Define the API URL and authorization header. Use an empty header map only when `ASSISTANT_BEARER_TOKEN` is not configured:

```powershell
$assistantBase = 'http://localhost:8000/api/v1/assistant'
$assistantToken = '<same-token-configured-as-ASSISTANT_BEARER_TOKEN>'
$assistantHeaders = @{ Authorization = "Bearer $assistantToken" }

Invoke-RestMethod `
  -Uri "$assistantBase/capabilities" `
  -Headers $assistantHeaders
```

An enabled provider reports:

```json
{
  "provider": "planttalk_openai",
  "modalities": ["text", "audio_input", "audio_output"],
  "transports": ["webrtc"],
  "available": true,
  "unavailable_reason": null
}
```

When the provider is disabled, `available` is `false`; core API readiness is unaffected.

Confirm the intended node exists before creating a session:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/devices
```

## Create A Session

```powershell
$sessionBody = @{ node_id = 'pi-001' } | ConvertTo-Json
$session = Invoke-RestMethod `
  -Method Post `
  -Uri "$assistantBase/sessions" `
  -Headers $assistantHeaders `
  -ContentType 'application/json' `
  -Body $sessionBody

$session | Select-Object session_id, provider, expires_at, transport
```

The response has this shape:

```json
{
  "session_id": "opaque-local-session-id",
  "provider": "planttalk_openai",
  "expires_at": "2026-07-12T16:00:00Z",
  "transport": "webrtc",
  "bootstrap": {
    "client_secret": "ek_short_lived_secret",
    "realtime_url": "https://api.openai.com/v1/realtime/calls",
    "model": "gpt-realtime"
  }
}
```

Treat both `session_id` and `bootstrap.client_secret` as credentials. Keep them in memory, do not log or persist them, and discard them at expiry. API restarts clear the local session registry, so existing `session_id` values then return `session_not_found`.

## Call Read-Only Tools

Tool endpoints use the local `session_id`, not the OpenAI client secret:

```powershell
$toolBody = @{
  session_id = $session.session_id
  arguments = @{}
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "$assistantBase/tools/get_current_state" `
  -Headers $assistantHeaders `
  -ContentType 'application/json' `
  -Body $toolBody
```

Replace `get_current_state` with any allow-listed tool name. Tool arguments are currently empty; passing a node override or other arguments returns `tool_not_allowed`.

Example response:

```json
{
  "session_id": "opaque-local-session-id",
  "tool_name": "get_current_state",
  "data": {
    "node_id": "pi-001",
    "result": {
      "schema_version": "state_v1",
      "node_id": "pi-001"
    }
  }
}
```

## Connect A Realtime Client

A browser or other WebRTC client uses `bootstrap.client_secret` to authenticate its SDP request to `bootstrap.realtime_url`. Text and audio turns share the instructions, selected-node context, and tool definitions attached when the session was created.

Follow the official [OpenAI Realtime WebRTC guide](https://developers.openai.com/api/docs/guides/realtime-webrtc) for peer-connection, audio-track, SDP, and `oai-events` data-channel handling. The planned #103 web application will provide this client flow under `/assistant`; until then, Senior Pomidor exposes the backend bootstrap and tool APIs only.

## Disable Or Rotate Credentials

To disable session creation, remove or clear `ASSISTANT_PROVIDER` and recreate the API container. Telemetry ingestion, state estimation, photos, and normal read APIs are unaffected.

To rotate credentials:

1. Replace `OPENAI_API_KEY` and/or `ASSISTANT_BEARER_TOKEN` in `.env`.
2. Recreate the API service with `docker compose up -d --force-recreate api`.
3. Verify `/api/v1/assistant/capabilities` with the new bearer token.
4. Discard existing local and Realtime session credentials.

Never paste either long-lived token into an issue, log, command history, browser source, or committed file.

## Troubleshooting

Assistant API failures use `{"error":{"code","message","retryable"}}`.

| HTTP | Code | Likely cause and action |
| --- | --- | --- |
| 400 | `invalid_node` | The node identifier is malformed; use an ID returned by `/api/v1/devices`. |
| 401 | `unauthorized` | The assistant bearer token is missing or incorrect. |
| 404 | `node_not_found` | The selected node has not stored telemetry or photos yet. |
| 404 | `session_not_found` | The ID is unknown or the API restarted; create a new session. |
| 404 | `tool_not_allowed` | The tool is not allow-listed or arguments were supplied. |
| 410 | `expired_session` | Create a replacement session and reconnect. |
| 429 | `rate_limited` | Wait for the configured local window or provider limit, then retry. |
| 503 | `configuration` | Check provider name, API key, model, voice, and OpenAI account access. |
| 503 | `unavailable` | Check outbound connectivity and OpenAI service availability. |
| 504 | `timeout` | Check connectivity or increase `ASSISTANT_PROVIDER_TIMEOUT_SECONDS` within its allowed range. |

Provider error bodies are normalized and are not forwarded to clients. Use capabilities first, confirm the node exists, and inspect API container health without logging request bodies or credentials.

## Development Verification

Assistant tests mock OpenAI and make no paid API calls:

```powershell
python -m pytest -p no:cacheprovider tests/test_assistant.py tests/test_assistant_api.py -q
python -m pytest -p no:cacheprovider tests/test_compose_config.py -q
```

The active wire contract and stable error codes are defined in [CONTRACTS.md](CONTRACTS.md).
