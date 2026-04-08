---
name: oya-messenger-script
display_name: "Oya Messenger Conversation Script"
description: "Master controller for Oya's live Instagram Messenger onboarding conversations — orchestrates GMB lookup, qualification, returning/current customer checks, lead info collection, onboarding form submission, and conversation close in strict script order"
category: sales
icon: message-circle
skill_type: sandbox
catalog_type: addon
requirements: "httpx>=0.25"
resource_requirements:
  - env_var: XANO_MCP_STREAM_URL
    name: "Xano MCP Stream URL"
    description: "Xano MCP server stream endpoint (e.g. https://xktx-zdsw-4yq2.n7.xano.io/x2/mcp/hEfoWGi_/mcp/stream)"
  - env_var: XANO_MCP_SSE_URL
    name: "Xano MCP SSE URL"
    description: "Xano MCP server SSE endpoint (e.g. https://xktx-zdsw-4yq2.n7.xano.io/x2/mcp/hEfoWGi_/mcp/sse)"
  - env_var: GOOGLE_PLACES_API_KEY
    name: "Google Places API Key"
    description: "Google Cloud API key with Places API enabled, used for GMB lookup"
  - env_var: ONBOARDING_LOGIN_LINK
    name: "Onboarding Login Link"
    description: "URL to send existing customers to log in (e.g. https://local.jumpermedia.co/login)"
tool_schema:
  name: oya-messenger-script
  description: "Master controller for Oya's Instagram Messenger onboarding script. Handles conversation state, orchestrates sub-skill calls, and returns the exact message Oya should send next plus any action directives."
  parameters:
    type: object
    properties:
      action:
        type: "string"
        description: "Which script operation to perform"
        enum:
          - trigger_welcome
          - gmb_lookup
          - confirm_gmb
          - check_xano_gmb
          - check_xano_email
          - run_qualification
          - collect_lead_info
          - submit_onboarding_form
          - close_conversation
          - redirect_offtopic
      lead_first_name:
        type: "string"
        description: "Lead's first name from Messenger profile (optional, omit if unavailable)"
        default: ""
      gmb_name_raw:
        type: "string"
        description: "Full assembled GMB business name as typed by the lead (used in gmb_lookup)"
        default: ""
      gmb_address_hint:
        type: "string"
        description: "Address provided by lead to disambiguate multiple GMB results (optional)"
        default: ""
      place_id:
        type: "string"
        description: "Google Places place_id of the confirmed GMB listing"
        default: ""
      confirmed_gmb_name:
        type: "string"
        description: "Business name exactly as returned by Google Places API"
        default: ""
      confirmed_gmb_address:
        type: "string"
        description: "Full address exactly as returned by Google Places API"
        default: ""
      lead_full_name:
        type: "string"
        description: "Lead's full name collected in Step 5"
        default: ""
      lead_email:
        type: "string"
        description: "Lead's email address collected in Step 5"
        default: ""
      lead_phone:
        type: "string"
        description: "Lead's phone number with country code collected in Step 5"
        default: ""
      confirmation_text:
        type: "string"
        description: "The lead's message when confirming their GMB listing (e.g. 'yes', 'yep', 'that's it')"
        default: ""
    required: [action]
---
# Oya Messenger Conversation Script

Master controller for **Oya's** live Instagram Messenger onboarding conversations at Jumper Media. Orchestrates the full script in strict order: welcome → GMB lookup → returning/current customer check → qualification → lead info collection → onboarding form → close.

Xano is accessed via MCP server endpoints:
- Stream: `https://xktx-zdsw-4yq2.n7.xano.io/x2/mcp/hEfoWGi_/mcp/stream`
- SSE: `https://xktx-zdsw-4yq2.n7.xano.io/x2/mcp/hEfoWGi_/mcp/sse`

---

## Actions

### trigger_welcome
Send the opening welcome message the moment a lead sends **RANK**.

**Parameters:** `lead_first_name` (optional)
**Returns:** `message` — the exact text Oya should send.