---
name: jumper-media-fb-onboarding
display_name: "Jumper Media FB Messenger Onboarding Agent"
description: "Session-aware Facebook Messenger onboarding agent that greets Map Pack trial leads, qualifies their Google Business Profile, collects contact info, suggests target keywords, and books an AE review call — routing every reply through the Meta Graph API"
category: sales
icon: user-check
skill_type: sandbox
catalog_type: addon
requirements: "httpx>=0.25 psycopg2-binary"
resource_requirements:
  - env_var: FB_PAGE_ACCESS_TOKEN
    name: "Facebook Page Access Token"
    description: "Meta Graph API page access token (Meta Business Suite > Settings > Page Access Token)"
  - env_var: GOOGLE_PLACES_API_KEY
    name: "Google Places API Key"
    description: "Google Maps Platform API key with Places API enabled (console.cloud.google.com)"
  - env_var: RETOOL_DB_URL
    name: "Retool PostgreSQL Connection URL"
    description: "Full PostgreSQL connection string for the Retool DB that stores fb_lead_sessions and fb_chat_leads tables"
  - env_var: CALENDLY_AE_URL
    name: "Calendly AE Review Call URL"
    description: "Calendly booking link for the Account Executive review call (optional — defaults to the Jumper Media link)"
tool_schema:
  name: jumper-media-fb-onboarding
  description: "Drive the full Jumper Media Facebook Messenger onboarding flow for Google Map Pack trial leads. Use action='handle_message' for every inbound Messenger message. Use action='send_message' to push a text to a user. Use action='qualify' to process a lead qualification step. Use action='suggest_keywords' to generate or confirm target keywords. Use action='book_ae_call' to send the Calendly link and create the CRM lead."
  parameters:
    type: object
    properties:
      action:
        type: "string"
        description: "Operation to perform"
        enum: ["handle_message", "send_message", "qualify", "suggest_keywords", "book_ae_call"]
      sender_id:
        type: "string"
        description: "Facebook Messenger PSID of the user"
        default: ""
      message:
        type: "string"
        description: "The user's raw inbound message text"
        default: ""
      recipient_id:
        type: "string"
        description: "Facebook Messenger PSID — for send_message action"
        default: ""
      text:
        type: "string"
        description: "Text to send — for send_message action"
        default: ""
      quick_replies:
        type: "array"
        description: "Optional quick reply buttons [{title, payload}] — for send_message action"
        default: []
    required: ["action"]
---
# Jumper Media FB Messenger Onboarding Agent

Session-aware Facebook Messenger onboarding agent that greets Google Map Pack trial leads, qualifies their Google Business Profile via the Places API, collects contact info, suggests target keywords, and books an AE review call — routing every reply through the Meta Graph API.

## Actions

### handle_message ← **Use this for every inbound Messenger message**
The master dispatcher. Pass the sender's PSID and their raw message. The skill reads the session state, calls the correct sub-flow, sends the reply via Messenger, and returns the updated step.