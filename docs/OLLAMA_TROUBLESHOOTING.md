# Ollama Troubleshooting Guide

This guide is a general diagnostic playbook for local Ollama installations. It is not tied to a particular
application, prompt, model, operating system, or programming language.

Last verified: 2026-07-16.

## The Four Layers of an Ollama Failure

Treat an Ollama request as four separate systems:

1. **Client and transport**: request serialization, endpoint, timeout, streaming, and HTTP error handling.
2. **Ollama server**: model discovery, scheduling, memory estimates, model loading, and API response construction.
3. **Native runner**: `llama-server`, llama.cpp/ggml, CPU/GPU backends, grammars, and model architecture support.
4. **Model behavior**: instruction following, thinking, output length, JSON quality, and hallucination.

Do not try to solve every failure by changing the prompt. A native runner assertion, malformed request, and short but
valid model answer have different causes and require different fixes.

## Fast Decision Tree

```text
Can GET /api/version and `ollama list` succeed?
|
+-- No  -> server/install/network problem; inspect server logs.
|
`ollama run MODEL "Say OK"` or a minimal /api/generate request succeeds?
|
+-- No  -> model load, hardware backend, corrupt model, or native runner problem.
|         Retry once CPU-only and inspect the complete server assertion.
|
Minimal request works without `format`, `think`, images, or custom options?
|
+-- No  -> model/runtime compatibility or resource problem.
|
Adding `format` fails with HTTP 400 and "grammar"?
|
+-- Yes -> schema-to-grammar incompatibility; simplify the schema.
|
HTTP 200 but `response` is empty?
|
+-- Yes -> inspect `thinking`; verify top-level `think`, token budget, and raw response.
|
Output is valid but too short?
|
+-- Yes -> inspect `done_reason`:
|          `length` => raise output/context budget.
|          `stop`   => improve instructions, validate, and perform an expansion rewrite.
|
HTTP 500 says runner terminated or contains GGML_ASSERT?
|
+-- Yes -> native backend failure; isolate CPU vs GPU and report the exact assertion upstream.
```

## Collect Evidence Before Changing Anything

Record the following for every reproducible failure:

```text
Operating system and version:
Ollama version:
Exact model tag and model ID:
Model architecture and quantization:
Request endpoint and non-secret request fields:
HTTP status and complete error body:
Server log assertion:
CPU/GPU model placement:
Context size and output-token limit:
Whether plain, CPU-only, and structured requests work:
```

Useful Ollama and NVIDIA commands on Windows or Linux:

```console
ollama --version
ollama list
ollama ps
ollama show MODEL
ollama show MODEL --modelfile
nvidia-smi
```

Additional Linux host and accelerator inventory:

```bash
uname -a
lscpu
free -h
lsblk
lspci -nn | grep -Ei 'vga|3d|display'
nvidia-smi                 # NVIDIA
rocminfo                   # AMD ROCm, when installed
vulkaninfo --summary       # Vulkan, when installed
```

`ollama ps` is particularly important. Its `PROCESSOR` column distinguishes `100% CPU`, `100% GPU`, and mixed
placement such as `87%/13% CPU/GPU`. Ollama documents this behavior in its
[FAQ](https://docs.ollama.com/faq#how-can-i-tell-if-my-model-was-loaded-onto-the-gpu).

### Log locations

Windows:

```powershell
Get-Content -LiteralPath "$env:LOCALAPPDATA\Ollama\server.log" -Tail 250
Get-Content -LiteralPath "$env:LOCALAPPDATA\Ollama\app.log" -Tail 100
```

Linux with systemd:

```bash
journalctl -u ollama --no-pager --follow --pager-end
```

Show only recent errors from the current boot:

```bash
journalctl -u ollama -b --no-pager -p warning
journalctl -u ollama -b --since "15 minutes ago" --no-pager
```

macOS:

```bash
tail -n 250 ~/.ollama/logs/server.log
```

Docker:

```bash
docker logs --tail 250 OLLAMA_CONTAINER
```

The official [troubleshooting documentation](https://docs.ollama.com/troubleshooting) lists platform-specific log
locations and debug settings. On Windows, quit the tray application before starting it with `OLLAMA_DEBUG=1`; changing
an environment variable in a terminal does not reconfigure an already running tray process.

For a temporary foreground debug session on Linux, stop the system service first so both processes do not compete for
port `11434`:

```bash
sudo systemctl stop ollama
OLLAMA_DEBUG=1 ollama serve
```

Press `Ctrl+C` when finished, then restore the normal service:

```bash
sudo systemctl start ollama
sudo systemctl status ollama --no-pager
```

To enable debug logging persistently for a systemd installation:

```bash
sudo systemctl edit ollama
```

Add the following override, save, and exit:

```ini
[Service]
Environment="OLLAMA_DEBUG=1"
```

Then reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
journalctl -u ollama --no-pager --follow --pager-end
```

### Preserve the complete error body

Do not log only the exception class or HTTP reason phrase. Read the response body once and preserve a safely bounded,
redacted copy. Some runner failures are wrapped twice: the outer Ollama `error` value may itself be a JSON-encoded
string containing an inner error object. Parse the outer object first and, only when appropriate, parse the inner string
as JSON. Keep the original body for diagnostics because flattening it can hide the native assertion.

For streaming requests, an error can arrive as a later NDJSON object after the HTTP response has already started. A
streaming client must inspect every object for an `error` field instead of relying only on the initial status code.

Linux example that preserves the body even for an HTTP error:

```bash
body_file=$(mktemp)
status=$(
  curl --silent --show-error \
    --output "$body_file" \
    --write-out '%{http_code}' \
    http://127.0.0.1:11434/api/generate \
    -H 'Content-Type: application/json' \
    -d '{"model":"MODEL","prompt":"Reply with OK.","stream":false}'
)

printf 'HTTP %s\n' "$status"
cat "$body_file"
rm -f "$body_file"
```

Use `trap` in automation so temporary files are removed if the script is interrupted. Redact sensitive prompt content
before attaching the captured request or response to an issue.

## Build a Minimal Reproduction Ladder

Add one feature at a time. Stop at the first failing step.

### 1. Check the API

Windows PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/version
```

Linux:

```bash
curl --fail-with-body --silent --show-error \
  http://127.0.0.1:11434/api/version
```

### 2. Test plain text without custom options

Windows PowerShell:

```powershell
$body = @{
    model = "MODEL"
    prompt = "Reply with OK."
    stream = $false
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri http://127.0.0.1:11434/api/generate `
    -Method Post `
    -ContentType application/json `
    -Body $body
```

Linux:

```bash
curl --fail-with-body --silent --show-error \
  http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON'
{
  "model": "MODEL",
  "prompt": "Reply with OK.",
  "stream": false
}
JSON
```

### 3. Disable thinking explicitly

Add this as a top-level request field:

```json
{
  "think": false
}
```

Linux request:

```bash
curl --fail-with-body --silent --show-error \
  http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON'
{
  "model": "MODEL",
  "prompt": "Reply with OK and no reasoning trace.",
  "stream": false,
  "think": false
}
JSON
```

### 4. Test generic JSON mode

```json
{
  "format": "json"
}
```

Linux request:

```bash
curl --fail-with-body --silent --show-error \
  http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON'
{
  "model": "MODEL",
  "prompt": "Return a JSON object with an answer field set to OK.",
  "stream": false,
  "think": false,
  "format": "json"
}
JSON
```

### 5. Test the smallest useful schema

```json
{
  "format": {
    "type": "object",
    "properties": {
      "answer": {"type": "string", "minLength": 1}
    },
    "required": ["answer"],
    "additionalProperties": false
  }
}
```

Linux request:

```bash
curl --fail-with-body --silent --show-error \
  http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON'
{
  "model": "MODEL",
  "prompt": "Return an object whose answer field is OK.",
  "stream": false,
  "think": false,
  "format": {
    "type": "object",
    "properties": {
      "answer": {"type": "string", "minLength": 1}
    },
    "required": ["answer"],
    "additionalProperties": false
  },
  "options": {"temperature": 0, "num_predict": 32}
}
JSON
```

### 6. Test CPU-only execution

```json
{
  "options": {
    "num_gpu": 0,
    "num_ctx": 2048,
    "num_predict": 32
  }
}
```

Linux request:

```bash
curl --fail-with-body --silent --show-error \
  http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON'
{
  "model": "MODEL",
  "prompt": "Reply briefly about a tomato.",
  "stream": false,
  "think": false,
  "keep_alive": "5m",
  "options": {
    "num_gpu": 0,
    "num_ctx": 2048,
    "num_predict": 32
  }
}
JSON
```

Check placement while the model remains loaded:

```bash
ollama ps
watch -n 1 ollama ps
```

### 7. Add the real prompt and budgets

Only after the previous steps work should the reproduction include the production system prompt, full context,
images, long output limit, schema constraints, or automatic GPU placement.

This ladder distinguishes four common cases:

| Plain | CPU-only | Schema | Likely cause |
|---|---|---|---|
| Fails | Fails | Not tested | Model/runtime incompatibility, corrupt model, or insufficient system memory |
| Fails automatically | Works | Works | GPU discovery, offload, or graph-splitting problem |
| Works | Works | Fails | Schema-to-grammar problem |
| Works | Works | Works, but content is wrong | Prompt/model behavior or application validation problem |

## HTTP 400: Failed to Parse Grammar

Typical error:

```text
Failed to initialize samplers: failed to parse grammar
```

### Cause

Ollama converts a JSON Schema supplied through `format` into a native grammar. The underlying llama.cpp converter
supports a subset of JSON Schema, and support can vary between bundled runner versions. A schema can be valid JSON
Schema while still being unsuitable for the runtime grammar compiler.

One confirmed example is a very large string bound such as:

```json
{"type": "string", "minLength": 1, "maxLength": 32768}
```

In one tested Ollama/runner version, `minLength: 1` compiled successfully while `maxLength: 32768` caused the grammar
parser to fail. Treat this as version-dependent behavior, not a universal boundary.

### Resolution

1. Replace the schema temporarily with `"format": "json"`.
2. Try the minimal object schema shown above.
3. Add properties and constraints one at a time.
4. Remove large `maxLength`, complex regex patterns, deep unions, and unnecessary schema metadata first.
5. Keep structural constraints in the grammar, but enforce business rules after parsing.
6. Validate the parsed result with Pydantic, Zod, JSON Schema, or equivalent application code.

Ollama recommends supplying the schema through `format`, grounding the model by describing the expected structure in
the prompt, and validating the result afterward. See [Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs).
llama.cpp also documents that JSON Schema conversion targets only a subset of the specification in its
[grammar guide](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md#json-schemas--gbnf).

### Do not use grammar length as a prose-quality control

A grammar can require a long JSON string, but it cannot tell whether the characters are a good answer. If a model
finishes its answer before a large `minLength` is satisfied, it may pad the constrained string with repetition,
planning, prompt analysis, or internal reasoning. Use grammar constraints for structure and application validation for
semantic length and quality.

## Empty `response`, Malformed JSON, or Thinking in the Wrong Field

### Correct request shape

`think` belongs at the top level of the request. It is not a generation option:

```json
{
  "model": "deepseek-r1:14b",
  "prompt": "Return the requested object.",
  "stream": false,
  "think": false,
  "options": {
    "temperature": 0
  }
}
```

Do not send this:

```json
{
  "options": {
    "think": "false"
  }
}
```

The latter is both in the wrong location and uses a string instead of a Boolean. A thinking model may then put all
generated tokens in `thinking` while leaving `response` empty.

Ollama's [Thinking documentation](https://docs.ollama.com/capabilities/thinking) states that most thinking models use
top-level Boolean values. Some model families use named thinking levels instead, so inspect the model's capabilities
and current documentation rather than assuming every model accepts `false`.

### Diagnostic procedure

1. Log `repr(response)` or the JSON-escaped value, not only a normal `print`.
2. Log the length of both `response` and `thinking`.
3. Check `done_reason` and `eval_count`.
4. Retry with `think: false` and a tiny prompt.
5. Retry without a schema to separate reasoning-template problems from grammar problems.
6. Inspect `ollama show MODEL --modelfile` for the model template and declared capabilities.

Always parse and validate the final response. HTTP 200 means the inference request completed; it does not guarantee that
the response satisfies the application's contract.

## Valid Output Is Too Short

Generation limits are ceilings, not minimums. `num_predict: 2048` permits up to 2,048 output tokens; it does not force
the model to use them.

Use the final response metrics:

| Metric | Interpretation |
|---|---|
| `done_reason: "length"` | The output budget was exhausted; increase `num_predict` and ensure `num_ctx` has room |
| `done_reason: "stop"` | The model chose to stop; raising only `num_predict` usually changes nothing |
| Low `eval_count` with `stop` | The prompt/model strongly preferred a short answer |
| High `prompt_eval_count` | Input is large; verify that input plus expected output fits the context |

The meanings of `prompt_eval_count`, `eval_count`, and duration fields are documented in Ollama's
[API usage guide](https://docs.ollama.com/api/usage). Durations are nanoseconds.

### Reliable long-form strategy

1. Make all length requirements consistent. Do not simultaneously request 900 words and six 280-character posts.
2. Specify concrete structure, such as a section or post count and an approximate size per section.
3. Validate character count, section count, required ending, and forbidden meta-commentary after parsing.
4. If the answer is short, include the previous draft in a corrective request and ask for a complete rewrite and
   expansion. Repeating the original prompt with the same seed often reproduces the same short answer.
5. Bound validation retries. Two or three changed attempts are usually more useful than many identical attempts.
6. Consider a model that follows length instructions better instead of indefinitely increasing sampling limits.

Example corrective instruction:

```text
The previous draft was 940 characters; the minimum is 1,680.
Rewrite and expand the whole answer into 7-10 clearly separated sections.
Preserve grounded facts, add relevant explanation, and return only the finished answer.

<draft>
...
</draft>
```

## Reasoning or Prompt Analysis Leaks into the Answer

Symptoms include phrases such as:

```text
The user wants me to...
I need to follow the system prompt...
Now I will craft the JSON response...
The previous attempt was invalid...
```

### Common causes

- Thinking was not disabled correctly.
- The client published the `thinking` field instead of `response`.
- A large grammar-enforced minimum prevented the model from closing the answer, so it used reasoning as padding.
- The model ignored the response boundary or placed analysis around an otherwise valid answer.

### Resolution

1. Set top-level `think: false` for models that support it.
2. Consume only `response`/message content, never the thinking trace, for publishable output.
3. Reduce grammar constraints to structural requirements such as a non-empty string.
4. Explicitly prohibit planning, prompt discussion, self-review, and commentary in the published field.
5. Require a deterministic terminal marker or structural field and reject trailing content.
6. Add high-confidence leak detection for phrases that cannot be valid domain content.
7. Retry with a changed corrective prompt; do not silently trim unknown trailing text unless that behavior is safe.

Thinking and constrained output are still evolving together in llama.cpp. Upstream reports document cases where
reasoning and grammar enforcement interact incorrectly; see
[llama.cpp issue #20345](https://github.com/ggml-org/llama.cpp/issues/20345).

## Requests Time Out on Large Models

Timeouts are usually capacity-planning failures, not transport failures, when all of the following are true:

- The model loads successfully.
- CPU usage remains active.
- The prompt contains thousands of tokens.
- The model is mostly or entirely CPU-resident.
- Small probes finish, while the real prompt exceeds the client deadline.

### Estimate runtime instead of guessing

From a successful probe:

```text
prompt tokens/second = prompt_eval_count / (prompt_eval_duration / 1e9)
output tokens/second = eval_count / (eval_duration / 1e9)
estimated request time = load time + prompt time + expected output time
```

Add operational margin for model loading, grammar sampling, retries, and system contention. A 14B quantized model on a
laptop CPU can take tens of minutes for a large prompt even when a 3B model finishes in several minutes.

### Resolution order

1. Remove accidental `num_gpu: 0` if a usable GPU is present.
2. Check actual placement with `ollama ps`; do not infer GPU use from installation alone.
3. Reduce prompt size without discarding necessary instructions.
4. Set `num_ctx` to the required input-plus-output budget rather than the model's maximum.
5. Set `num_predict` to a realistic output ceiling.
6. Use a smaller or more aggressively quantized model.
7. Use a longer per-model timeout based on measured throughput.
8. Use `keep_alive` to avoid repeated model loading, while recognizing that it does not speed prompt evaluation or
   token generation.
9. Avoid automatically repeating a 30-minute timeout several times without changing the cause.

Larger contexts consume more memory. Ollama's [context-length guide](https://docs.ollama.com/context-length) and
[FAQ](https://docs.ollama.com/faq#how-can-i-specify-the-context-window-size) explain context configuration and memory
scaling. Parallel requests multiply context memory requirements.

## Native Runner HTTP 500 and `GGML_ASSERT`

Typical errors:

```text
HTTP 500: llama-server process has terminated
GGML_ASSERT(...)
exit status 0xc0000409
```

An HTTP 500 with a native assertion is below the application and prompt layers. Retrying the same request unchanged
usually launches the same runner path and reproduces the crash.

On Windows, `0xc0000409` may be rendered as "stack-based buffer overrun." When the server log immediately shows a
`GGML_ASSERT`, this is normally Windows' description of the process abort status, not evidence that the prompt launched
an exploit. Preserve the exact assertion and native runner build information.

### Isolate CPU versus GPU

Run this matrix with a tiny prompt and token budget:

| Test | Meaning |
|---|---|
| Automatic placement fails, `num_gpu: 0` works | GPU discovery, offload, graph split, or backend bug |
| Both automatic and CPU-only fail | Architecture/runtime incompatibility, model corruption, or RAM problem |
| Plain output works, schema fails | Grammar/sampler path problem |
| Small context works, large context fails | Memory allocation or context-size problem |

### Gemma 4 scheduler crash example

One confirmed Gemma 4 failure occurred during automatic layer fitting on a low-VRAM GPU:

```text
GGML_ASSERT(n_inputs < GGML_SCHED_MAX_SPLIT_INPUTS) failed
```

CPU-only inference worked. Explicit small GPU-layer counts also worked, while automatic fitting crashed even with a
small context and no schema. This exact Gemma 4 assertion has also been reported upstream in
[llama.cpp issue #21730](https://github.com/ggml-org/llama.cpp/issues/21730). Gemma 4 GPU/offload behavior has separate
reports in [Ollama issue #15237](https://github.com/ollama/ollama/issues/15237).

Recommended response:

1. Upgrade Ollama and the GPU driver, then retest the minimal reproduction.
2. If automatic fitting still crashes, try `num_gpu: 0`.
3. If partial acceleration is important, test explicit conservative `num_gpu` values from low to high.
4. Never copy a layer count from another machine without testing; model architecture, quantization, context, free VRAM,
   and backend all affect the safe value.
5. For a portable client, try automatic placement first and perform one CPU fallback only when a known native-runner
   signature is present.
6. Respect explicit user placement. Do not override an intentionally configured `num_gpu`.
7. Record the fallback in metrics so operators know the request ran more slowly on CPU.

Linux probe for CPU-only and conservative explicit layer counts:

```bash
MODEL='gemma4:latest'

for layers in 0 1 5 10; do
  printf '\n=== num_gpu=%s ===\n' "$layers"
  curl --fail-with-body --silent --show-error \
    http://127.0.0.1:11434/api/generate \
    -H 'Content-Type: application/json' \
    -d "{
      \"model\": \"$MODEL\",
      \"prompt\": \"Reply briefly about a tomato.\",
      \"stream\": false,
      \"think\": false,
      \"keep_alive\": \"5m\",
      \"options\": {
        \"num_gpu\": $layers,
        \"num_ctx\": 2048,
        \"num_predict\": 16
      }
    }" || true
  ollama ps
done
```

Start low. Stop increasing the layer count when a request fails, VRAM is exhausted, or the runner becomes unstable.
Run this probe without other inference workloads so changing free VRAM does not invalidate the comparison.

On a machine with no GPU, Ollama normally chooses CPU execution on the first request. A robust fallback should not
require GPU detection; it should activate only after a matching automatic-placement crash.

The official [hardware guide](https://docs.ollama.com/gpu) covers supported GPUs, driver requirements, GPU selection,
and ways to force CPU execution at the server level.

## Retry Policy

Classify before retrying:

| Failure | Default policy |
|---|---|
| HTTP 400 invalid request/grammar | Do not retry unchanged; fix request or schema |
| HTTP 404 model missing | Pull or correct the model tag |
| HTTP 408/transport timeout | Retry only if transient; otherwise change timeout or workload |
| HTTP 409/425/429 | Bounded retry with backoff and jitter |
| HTTP 500 native assertion | Inspect logs; use a targeted fallback or change runtime/configuration |
| HTTP 500 transient server failure | Bounded retry with backoff |
| Malformed JSON | Retry with corrected schema/prompt; preserve raw response for diagnosis |
| Valid but semantically invalid output | Retry with validation feedback and the prior draft |
| Identical deterministic failure | Change prompt/options/model; do not repeat indefinitely |

Ollama documents common API status codes and streaming error behavior in its
[API error guide](https://docs.ollama.com/api/errors). Streaming errors may arrive inside the NDJSON stream after an
HTTP 200 response has already begun, so streaming clients must inspect every chunk for an `error` field.

### Portable native-crash fallback pseudocode

```text
response = request_with_automatic_placement()

if response is a matching model/backend runner crash
   and the caller did not explicitly configure GPU placement:
       response = retry_once(options + {num_gpu: 0})
       response.metrics.cpu_fallback = true

return response
```

Keep this narrow. A broad "retry every 500 on CPU" rule can hide corrupt models, RAM exhaustion, invalid runner builds,
and unrelated server bugs.

## Configuration Checklist

Before approving a model for production, test and record:

- Exact immutable model tag or model ID.
- Ollama version and upgrade policy.
- Model capabilities from `ollama show`.
- Plain, structured, thinking-disabled, and CPU-only requests.
- Minimum RAM and VRAM headroom.
- Actual CPU/GPU split from `ollama ps`.
- Maximum tested prompt and output sizes.
- Measured prompt and output tokens per second.
- Timeout and keep-alive values.
- Application-side schema and semantic validators.
- Retry limits and backoff.
- Whether CPU fallback is allowed and how it is surfaced.
- Log retention and redaction policy.

Do not put secrets, private documents, or full sensitive prompts into normal logs. Preserve request shape, lengths,
model identifiers, timing metrics, and redacted error bodies instead.

## Recommended Production Defaults

These are principles, not universal numeric values:

- Pin Ollama in production; test upgrades against every approved model.
- Pin model tags or IDs and record quantization.
- Use `stream: false` for short structured outputs unless streaming is necessary.
- Use top-level `think: false` when structured publishable output must not include reasoning and the model supports it.
- Start schemas small; constrain structure, then validate semantics in the application.
- Use low temperature for extraction and deterministic structured tasks.
- Budget `num_ctx` for input plus output with headroom.
- Treat `num_predict` as a maximum, never a minimum.
- Set timeouts per model and hardware class using measured throughput.
- Keep retries bounded and cause-aware.
- Expose `done_reason`, token counts, durations, placement/fallback state, and validation failures as metrics.
- Maintain a small smoke-test prompt for each approved model.

## When to File an Upstream Issue

File an Ollama or llama.cpp issue when a minimal request consistently causes a native runner crash, incorrect backend
selection, model load failure, or reproducible grammar bug on a current version.

Include:

```text
ollama --version
ollama show MODEL
ollama show MODEL --modelfile
ollama ps
OS and GPU driver version
CPU, RAM, GPU, and VRAM
Minimal redacted request JSON
Whether num_gpu=0 works
Whether no-format output works
Complete HTTP error body
Relevant server.log section including the first assertion
```

Search existing [Ollama issues](https://github.com/ollama/ollama/issues) and
[llama.cpp issues](https://github.com/ggml-org/llama.cpp/issues) using the exact assertion before opening a duplicate.

## Primary References

- [Ollama troubleshooting](https://docs.ollama.com/troubleshooting)
- [Ollama generate API](https://docs.ollama.com/api/generate)
- [Ollama API errors](https://docs.ollama.com/api/errors)
- [Ollama API usage metrics](https://docs.ollama.com/api/usage)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama thinking](https://docs.ollama.com/capabilities/thinking)
- [Ollama context length](https://docs.ollama.com/context-length)
- [Ollama FAQ](https://docs.ollama.com/faq)
- [Ollama hardware support](https://docs.ollama.com/gpu)
- [llama.cpp grammar and JSON Schema guide](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md)
- [Gemma 4 scheduler assertion report](https://github.com/ggml-org/llama.cpp/issues/21730)
