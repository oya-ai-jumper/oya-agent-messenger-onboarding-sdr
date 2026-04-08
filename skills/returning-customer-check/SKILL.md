---
name: returning-customer-check 
display_name: "Returning Customer Check"
description: "Silently checks whether a confirmed GMB listing already has an active Jumper Local account in Xano before onboarding proceeds, sending a login link if active, a reactivation scheduling link if expired, or returning new_lead status otherwise"
category: sales
icon: shield-check
skill_type: sandbox
catalog_type: addon
requirements: "httpx>=0.25"
resource_requirements:
  - env_var: XANO_MCP_API_KEY
    name: "Xano MCP API Key"
    description: "Bearer token or API key for authenticating with the Xano MCP server at https://xktx-zdsw-4yq2.n7.xano.io"
tool_schema:
  name: returning_customer_check
  description: "Silently checks whether a confirmed GMB already has an active Jumper Local account in Xano. Run immediately after GMB confirmation, before collecting lead info. Returns new_lead, active_customer, or expired_customer status."
  parameters:
    type: object
    properties:
      action:
        type: "string"
        description: "Operation to perform"
        enum: ["check_customer"]
      place_id:
        type: "string"
        description: "Google Place ID of the confirmed GMB listing (e.g. 'ChIJ...'). Primary lookup key."
        default: ""
      name:
        type: "string"
        description: "Exact business name from Google (used as fallback if place_id lookup returns no result)"
        default: ""
      formatted_address:
        type: "string"
        description: "Full formatted address from Google (used as fallback alongside business name)"
        default: ""
    required: ["action", "place_id"]
---
# Returning Customer Check

Silently checks whether a confirmed GMB listing already has an active Jumper Local subscription or trial in the Xano database. Run this immediately after GMB confirmation and before collecting any lead information (name, email, phone).

---

## Actions

### check_customer

Queries Xano via MCP server using `place_id` as the primary key, falling back to business name + address. Evaluates the subscription/trial status of any matching record.

Returns one of three statuses:

- `new_lead` — no record found in Xano, proceed with normal onboarding
- `active_customer` — existing active/trialing account, send login link
- `expired_customer` — existing record found but plan is inactive/expired, send reactivation scheduling link

**Example parameters:**

    {
      "action": "check_customer",
      "place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
      "name": "My Business",
      "formatted_address": "123 Main St, Springfield, IL 62701, USA"
    }