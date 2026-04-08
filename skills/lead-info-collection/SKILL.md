---
name: lead-info-collection
display_name: "Lead Info Collection"
description: "Collects full name, email, and phone number from a qualified lead in strict order during the Oya onboarding flow (Step 4)"
category: sales
icon: user-check
skill_type: sandbox
catalog_type: addon
requirements: "httpx>=0.25"
tool_schema:
  name: lead-info-collection
  description: "Collects full name, email, and phone number from a qualified lead in the Oya onboarding flow, one at a time in strict order: name → email → phone"
  parameters:
    type: object
    properties:
      action:
        type: "string"
        description: "Which step of collection to perform"
        enum: ["ask_name", "store_name", "ask_email", "store_email", "ask_phone", "store_phone", "get_collected_data"]
      lead_name:
        type: "string"
        description: "The full name provided by the lead — required for store_name"
        default: ""
      lead_email:
        type: "string"
        description: "The email address provided by the lead — required for store_email"
        default: ""
      lead_phone:
        type: "string"
        description: "The phone number provided by the lead — required for store_phone"
        default: ""
      session_id:
        type: "string"
        description: "Unique identifier for this lead session, used to persist collected data across steps"
        default: ""
    required: [action]
---
# Lead Info Collection

Collects full name, email, and phone number from a qualified lead in strict order during the Oya onboarding flow. Always run after `gmb-qualification-check` passes, and before proceeding to the onboarding form navigation (Step 5).

## Actions

### ask_name
Returns the exact message to send to the lead asking for their full name.
- action: ask_name
- Returns: `{ "message": "Whats your full name?", "field": "lead_name", "step": "4a" }`

### store_name
Stores the lead's full name exactly as provided.
- action: store_name, lead_name: "Jane Smith", session_id: "abc123"
- Returns: `{ "stored": true, "field": "lead_name", "value": "Jane Smith", "next_action": "ask_email" }`

### ask_email
Returns the exact message to send to the lead asking for their email address.
- action: ask_email
- Returns: `{ "message": "Perfect. I'll create your dashboard now. What's the best email for your login?", "field": "lead_email", "step": "4b" }`

### store_email
Stores the lead's email address exactly as provided.
- action: store_email, lead_email: "jane@example.com", session_id: "abc123"
- Returns: `{ "stored": true, "field": "lead_email", "value": "jane@example.com", "next_action": "ask_phone" }`

### ask_phone
Returns the exact message to send to the lead asking for their phone number.
- action: ask_phone
- Returns: `{ "message": "And what phone number can I text your login details to? (Please include your country code, e.g. +1)", "field": "lead_phone", "step": "4c" }`

### store_phone
Stores the lead's phone number exactly as provided.
- action: store_phone, lead_phone: "+15551234567", session_id: "abc123"
- Returns: `{ "stored": true, "field": "lead_phone", "value": "+15551234567", "next_action": "get_collected_data" }`

### get_collected_data
Returns all collected lead data, ready to pass to Step 5 (onboarding form navigation).
- action: get_collected_data, session_id: "abc123"
- Returns: `{ "lead_name": "Jane Smith", "lead_email": "jane@example.com", "lead_phone": "+15551234567", "ready_for_step_5": true }`

---

## Usage Tips

- **Always run in strict order**: ask_name → store_name → ask_email → store_email → ask_phone → store_phone → get_collected_data.
- **Never skip ahead**: do not ask for email or phone before storing the previous field.
- **Send exactly the message returned** by ask_name / ask_email / ask_phone — do not paraphrase or modify the wording.
- **Wait for the lead's reply** before calling the next store_* action. Do not call store_name until the lead has responded with their name.
- **Store exactly what the lead provides** — do not reformat, autocorrect, or paraphrase any value.
- **Use a consistent session_id** across all steps in the same conversation so data is persisted correctly.
- **Do not collect any other information** — no address, payment details, passwords, or additional fields.
- **Only run this skill after** `gmb-qualification-check` has confirmed all four criteria pass.
- **Always call get_collected_data last** to produce the final payload for Step 5.