---
name: retool-customer-mapper
display_name: "Retool Customer Mapper"
description: "Resolves a full customer profile from a Retool PostgreSQL database including contact info, deal details, GMB ID, and Xano keyword performance data"
category: sales
icon: database
skill_type: sandbox
catalog_type: addon
requirements: "httpx>=0.25 psycopg2-binary>=2.9"
tool_schema:
  name: retool_customer_mapper
  description: "Resolve a complete customer profile by email, phone, or name — returns contact, deal, GMB ID, and keyword performance data"
  parameters:
    type: object
    properties:
      client_identifier:
        type: "string"
        description: "Customer's email address, phone number, or full name"
      gmbs_id:
        type: "string"
        description: "Optional: override GMB/Google My Business location ID"
        default: ""
    required: [client_identifier]
---
# Retool Customer Mapper

Resolve a complete customer profile from the Retool PostgreSQL database by supplying an email, phone number, or full name. Returns contact info, deal details, GMB ID, and live keyword performance from Xano.

## Actions

### resolve_profile
Look up a customer by email, phone, or name.

Example inputs:
- `client_identifier: "jane.doe@example.com"`
- `client_identifier: "5551234567"`
- `client_identifier: "Jane Doe"`
- `client_identifier: "jane.doe@example.com", gmbs_id: "49013"` (override GMB ID)

Returns:
- Full contact profile (name, email, phone, CSR/SDR assignment, product, billing status)
- Deal details (ID, name, stage, value, close date)
- GMB ID (resolved from contact → deal → backfill table)
- Keyword performance list from Xano (keyword + performance %)
- Markdown-formatted profile summary

## Usage Tips

- **Be Proactive**: If the user mentions a customer name, email, or phone number in any context, proactively call this skill to pull their full profile before responding.
- When `gmbs_id` is available in the result, always display keyword performance as it reveals SEO health.
- Missing data is listed in the `missing` array — surface this to the user so they know what gaps exist.
- Phone numbers can be entered in any format (e.g. `555-123-4567`, `5551234567`, `+15551234567`) — the skill normalises them automatically.
- If multiple contacts match a name search, the first match is returned; mention this to the user.