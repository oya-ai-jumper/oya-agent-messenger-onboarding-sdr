---
name: oya-messenger-script
display_name: "Messenger Onboarding SDR"
description: "End-to-end Facebook Messenger onboarding for Jumper Local — single LLM-facing tool that drives the full SDR script as a Python state machine."
category: sales
icon: message-circle
skill_type: sandbox
catalog_type: addon
requirements: "httpx>=0.25, psycopg2-binary>=2.9"
entry_point: "scripts/script.py"
---
# Messenger Onboarding SDR

Single-tool skill that owns the entire Facebook Messenger onboarding flow. The parent agent calls `handle_message` once per inbound and sends the returned `reply` verbatim. All flow logic, verbatim copy, qualification thresholds, and integrations live inside this skill.

## CRITICAL — How to relay output to the parent agent

The script returns JSON of the form `{"reply": "<exact text>", "step": "..."}`.

When you (the standalone executor) receive this, your response to the parent agent MUST be the **exact `reply` text verbatim** — no paraphrasing, no quotes around it, no preamble like "The tool returned:". If `reply` is empty string, respond with the literal token `<<SILENT>>` so the parent knows to send nothing. If the script returns `{"error": "..."}`, respond with `<<SILENT>>` (do not surface technical errors to the lead).

## Tool

`handle_message(action="handle_message", sender_id, message_text, lead_first_name?)`

- `sender_id` — the lead'\''s real Messenger PSID. Never use `default_user`.
- `message_text` — the exact text the lead just sent.
- `lead_first_name` — first name from FB profile if available, else empty string.

## Activation

Only triggers on `MAPS` (case-insensitive) or an active session for the PSID. Other first-time messages return `{"reply": ""}`.

## State machine

| Step | Sends | Expects |
|---|---|---|
| `new` | — | MAPS |
| `welcome_sent` | welcome | GMB name |
| `gmb_proposed` | "X at Y. Is this your business?" | yes/no |
| `awaiting_address` | ask for address | address |
| `collecting_full_name` | ask for full name | name |
| `collecting_email` | ask for email | email |
| `collecting_phone` | ask for phone | phone |
| `awaiting_booking` | book-the-call message | (Calendly webhook) |
| `completed` | post-booking video message | — |
| `disqualified_*` / `returning_*_sent` | terminal — only `MAPS` reopens | — |

## Files

- `scripts/script.py` — entry, dispatches `handle_message`
- `scripts/handler.py` — orchestrator (state machine)
- `scripts/state.py` — SQLite session store
- `scripts/messages.py` — YAML loader for assets/messages.yaml + assets/urls.yaml
- `scripts/_legacy.py` — lower-level integrations (Google Places, Xano MCP, Slack, FB Graph)
- `assets/messages.yaml`, `assets/urls.yaml`, `assets/flow.yaml`
- `references/spec.md`, `references/persona.md`, `references/objections.md`
