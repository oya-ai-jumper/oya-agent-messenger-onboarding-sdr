---
name: gmb-qualification-check
display_name: "GMB Qualification Check"
description: "Silently validate a Google My Business listing against Jumper Media program thresholds (hours, website, review count, rating) and return the correct disqualification message or a pass result for re-entry and onboarding flows."
category: marketing
icon: search
skill_type: sandbox
catalog_type: addon
requirements: "httpx>=0.25"
resource_requirements:
  - env_var: GOOGLE_PLACES_API_KEY
    name: "Google Places API Key"
    description: "API key from Google Cloud Console with Places API enabled (used to re-fetch fresh GMB data for returning leads)"
tool_schema:
  name: gmb-qualification-check
  description: "Run the four-point GMB qualification check against Jumper Media program thresholds. Returns qualified=true (proceed silently) or a disqualification payload with the exact message to send the lead. Supports first-time checks and re-entry from previously disqualified leads."
  parameters:
    type: object
    properties:
      action:
        type: "string"
        description: "Which operation to perform"
        enum: ["check", "recheck"]
      place_id:
        type: "string"
        description: "Google Place ID from the gmb-lookup skill (e.g. 'ChIJ...'). Required for recheck to fetch fresh data."
        default: ""
      gmb_data:
        type: "object"
        description: "The GMB data object returned by the gmb-lookup skill. Required for action=check. Must contain: place_id, name, formatted_address, has_hours, website, review_count, rating."
        default: {}
      business_name:
        type: "string"
        description: "Business name — used as fallback identifier in re-entry acknowledgement messages."
        default: ""
    required: ["action"]
---
# GMB Qualification Check

Silently validate a confirmed Google My Business listing against Jumper Media program thresholds before collecting lead contact information. Returns a clean pass or a structured disqualification payload containing the exact message to deliver to the lead.

---

## Actions

### check
Run the four-point qualification check against a GMB data object already in memory (from `gmb-lookup`).

**Example parameters:**