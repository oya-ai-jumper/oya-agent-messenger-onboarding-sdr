---
name: gmb-lookup
display_name: "GMB Lookup (Google Places)"
description: "Search for and retrieve verified Google My Business listings by business name and/or address, returning full details including hours, website, rating, review count, and place ID"
category: marketing
icon: map-pin
skill_type: sandbox
catalog_type: addon
requirements: "httpx>=0.25"
resource_requirements:
  - env_var: GOOGLE_PLACES_API_KEY
    name: "Google Places API Key"
    description: "API key from Google Cloud Console with Places API enabled (console.cloud.google.com > APIs & Services > Credentials)"
tool_schema:
  name: gmb-lookup
  description: "Search for and retrieve verified Google My Business listings by business name and/or address, returning full details including hours, website, rating, review count, and place ID"
  parameters:
    type: object
    properties:
      action:
        type: "string"
        description: "Which operation to perform"
        enum: ["search", "details"]
      business_name:
        type: "string"
        description: "Full business name as it appears on Google Maps — required for search"
        default: ""
      address:
        type: "string"
        description: "Business address or city — optional for search, used to disambiguate multiple results"
        default: ""
      place_id:
        type: "string"
        description: "Google Place ID — required for details action (obtained from a prior search)"
        default: ""
    required: [action]
---
# GMB Lookup (Google Places)

Search for and retrieve verified Google My Business (GMB) listings using the Google Places API. Use this skill to find a business listing by name and/or address, confirm the correct listing, and retrieve full details including hours, website, rating, and review count.

## Actions

### search
Search for a business by name and optional address using the Google Places Text Search endpoint.

**Example — name only:**