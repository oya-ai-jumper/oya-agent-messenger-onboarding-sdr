---
name: jumper-local-onboarding
display_name: "Jumper Local Onboarding"
description: "Complete the Jumper Local onboarding flow via browser automation: submit GMB business info, fill lead contact details, and send a Calendly booking confirmation to the lead"
category: sales
icon: globe
skill_type: sandbox
catalog_type: addon
requirements: "httpx>=0.25,playwright>=1.40"
tool_schema:
  name: jumper-local-onboarding
  description: "Complete the Jumper Local onboarding flow and send the lead a Calendly booking link confirmation"
  parameters:
    type: object
    properties:
      action:
        type: "string"
        description: "Which operation to perform"
        enum: ["complete_onboarding", "send_confirmation"]
      gmb_name:
        type: "string"
        description: "Google My Business name exactly as returned by Google Places API"
        default: ""
      gmb_address:
        type: "string"
        description: "Google My Business address exactly as returned by Google Places API"
        default: ""
      lead_name:
        type: "string"
        description: "Full name of the lead"
        default: ""
      lead_email:
        type: "string"
        description: "Email address of the lead"
        default: ""
      lead_phone:
        type: "string"
        description: "Phone number of the lead"
        default: ""
    required: [action]
---
# Jumper Local Onboarding

Automates the Jumper Local onboarding flow by navigating to the internal onboarding portal, entering GMB business details, selecting the correct listing, filling in lead contact info, and then sending the lead a Calendly confirmation message to book their specialist call.

## Actions

### complete_onboarding
Navigates to the Jumper Local onboarding portal and completes all three steps: enters GMB name and address, selects the matching GMB from results, and fills in the lead's contact information.

**Example parameters:**