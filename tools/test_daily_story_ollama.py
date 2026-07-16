from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.daily_story import (  # noqa: E402
    build_daily_story_context,
    build_environment_context,
    generate_story,
    load_environment_context,
    load_prompts,
    render_user_prompt,
)
from app.ollama import OllamaClient  # noqa: E402

# Edit these values for the local test environment.
DATABASE_URL = "postgresql+psycopg://senior_pomidor:senior_pomidor@127.0.0.1:5432/senior_pomidor"
NODE_ID = "balcony-edge-01"
TIMEZONE = "Europe/Vienna"
LOOKBACK_HOURS = 24
MAX_CONTEXT_CHARS = 32_768
MAX_ENVIRONMENT_CONTEXT_CHARS = 8_000
MEMORY_ENTRIES = 7
SYSTEM_PROMPT_PATH = "../config/daily_story/system.txt"
USER_PROMPT_PATH = "../config/daily_story/user.txt"
ENVIRONMENT_CONTEXT_PATH = "../config/daily_story/environment.json"
OLLAMA_HOST = "http://127.0.0.1:11434"
# Large CPU-bound models such as phi4 can take 25-35 minutes for this prompt.
OLLAMA_TIMEOUT_SECONDS = 3600
KEEP_ALIVE = "5m"
RETRY_ATTEMPTS = 3
OPTIONS = {
    "temperature": 0.8,  # было 0.75
    "top_p": 0.92,  # было 0.9
    "top_k": 40,
    # The observed prompt is about 5,600 tokens, leaving room for 2,048 output tokens.
    "num_ctx": 8192,
    "num_predict": 2048,  # вместо 120
    "repeat_penalty": 1.12,  # было 1.1
    # seed убрать
}

if len(sys.argv) != 2:
    raise SystemExit(f"Usage: python {Path(__file__).name} MODEL")

model = sys.argv[1]
window_end = datetime.now(UTC)
window_start = window_end - timedelta(hours=LOOKBACK_HOURS)
base_environment_context = load_environment_context(ENVIRONMENT_CONTEXT_PATH, MAX_ENVIRONMENT_CONTEXT_CHARS)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
database_inspector = inspect(engine)
has_story_memory_schema = database_inspector.has_table("daily_story_runs") and any(
    column["name"] == "environment_context_jsonb" for column in database_inspector.get_columns("daily_story_runs")
)
with Session(engine) as db:
    context = build_daily_story_context(
        db,
        node_id=NODE_ID,
        window_start=window_start,
        window_end=window_end,
        max_chars=MAX_CONTEXT_CHARS,
    )
    if has_story_memory_schema:
        environment_context = build_environment_context(
            db,
            node_id=NODE_ID,
            story_date=window_end.astimezone(ZoneInfo(TIMEZONE)).date(),
            base_context=base_environment_context,
            memory_entries=MEMORY_ENTRIES,
            max_chars=MAX_ENVIRONMENT_CONTEXT_CHARS,
        )
    else:
        environment_context = json.loads(json.dumps(base_environment_context, ensure_ascii=False))
        running_memories = environment_context.get("running_memories")
        if isinstance(running_memories, list):
            running_memories = {"notes": running_memories}
        elif not isinstance(running_memories, dict):
            running_memories = {"notes": []}
        running_memories["previous_diary_entries"] = []
        environment_context["running_memories"] = running_memories
        print("Daily-story memory schema is unavailable; testing without previous diary entries.\n", file=sys.stderr)
engine.dispose()

system_prompt, user_template = load_prompts(SYSTEM_PROMPT_PATH, USER_PROMPT_PATH)
user_prompt = render_user_prompt(
    user_template,
    node_id=NODE_ID,
    window_start=window_start,
    window_end=window_end,
    environment_context=environment_context,
    summary=context.summary,
)

print("ENVIRONMENT_CONTEXT_JSON:")
print(json.dumps(environment_context, indent=2, ensure_ascii=False, sort_keys=True))
print()
print("CONTEXT_JSON:")
print(json.dumps(context.summary, indent=2, ensure_ascii=False, sort_keys=True))
print("\nSYSTEM PROMPT:")
print(system_prompt)
print("\nUSER PROMPT:")
print(user_prompt)

client = OllamaClient(host=OLLAMA_HOST, timeout_seconds=OLLAMA_TIMEOUT_SECONDS)
result = generate_story(
    client,
    model=model,
    system_prompt=system_prompt,
    user_prompt=user_prompt,
    options=OPTIONS,
    keep_alive=KEEP_ALIVE,
    retry_attempts=RETRY_ATTEMPTS,
)

print("\nSTORY:")
print(result.story)
print("\nOLLAMA METRICS:")
print(json.dumps(result.metrics, indent=2, sort_keys=True))
