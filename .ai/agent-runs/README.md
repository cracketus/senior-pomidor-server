# Agent run audit artifacts

Committed records use the `agent_run_v1` schema and contain only bounded references and aggregate
usage. Raw prompts, tool output, environment values, secrets, private infrastructure, and sensitive
payloads are prohibited. Validate records with `python -m tools.agent_audit <record.json>`.
