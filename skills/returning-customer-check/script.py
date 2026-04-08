import os
import sys
import json
import httpx
import psycopg2
import psycopg2.extras

# Safely reconfigure stdout to UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

print(f"A2ABASEAI_FILE: script.py")

XANO_MCP_STREAM = "https://xktx-zdsw-4yq2.n7.xano.io/x2/mcp/hEfoWGi_/mcp/stream"
RETOOL_DB_URL = os.environ.get(
    "RETOOL_DB_URL",
    "postgresql://retool:npg_H0EaIfvzmg3Q@ep-small-surf-a6occgdz-pooler.us-west-2"
    ".retooldb.com/retool?sslmode=require",
)

LOGIN_LINK_MESSAGE = (
    "It looks like your business already has an active Jumper Local account! "
    "You can sign in here: https://local.jumpermedia.co/signin\n\n"
    "If you need any help, feel free to reach out to our support team. \U0001f60a"
)

REACTIVATION_LINK_MESSAGE = (
    "Welcome back! It looks like your business previously had a Jumper Local account, "
    "but your plan is no longer active.\n\n"
    "To reactivate your GMB and get your Google rankings back on track, you can schedule "
    "a call with our team here: https://calendly.com/jmpsales/google-ranking-increase-jumper-local\n\n"
    "We'd love to help you get started again! \U0001f60a"
)

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_CLIENT_NAME = "returning-customer-check"
MCP_CLIENT_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Retool DB — resolve place_id → email
# ---------------------------------------------------------------------------

def get_email_by_place_id(place_id: str) -> str | None:
    """Look up the customer email in Retool by Google place_id."""
    try:
        conn = psycopg2.connect(RETOOL_DB_URL, connect_timeout=15)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT email FROM backfill_gmbs_names_and_other "
                    "WHERE place_id = %s AND email IS NOT NULL LIMIT 1",
                    (place_id,),
                )
                row = cur.fetchone()
                return row["email"] if row else None
        finally:
            conn.close()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Xano MCP — initialize with session ID, then call get_gmb
# ---------------------------------------------------------------------------

def xano_get_gmb(api_key: str, email: str, timeout: int = 20) -> dict | None:
    """
    Call Xano get_gmb tool by email.
    Includes mcp-session-id in all requests after initialize — required by Xano MCP server.
    Returns the GMB record dict, or None if not found.
    """
    base_headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    with httpx.Client(timeout=timeout) as c:
        # Step 1: initialize — get session ID from response header
        r1 = c.post(XANO_MCP_STREAM, headers=base_headers, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": MCP_CLIENT_NAME, "version": MCP_CLIENT_VERSION},
            },
        })
        if r1.status_code != 200:
            raise Exception(f"MCP initialize failed: {r1.status_code}")

        session_id = r1.headers.get("mcp-session-id", "")
        session_headers = {**base_headers, "mcp-session-id": session_id}

        # Step 2: notifications/initialized — must include session ID
        c.post(XANO_MCP_STREAM, headers=session_headers, json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        })

        # Step 3: call get_gmb with email — must include session ID
        r2 = c.post(XANO_MCP_STREAM, headers=session_headers, json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_gmb", "arguments": {"email": email}},
        })

        if r2.status_code != 200:
            raise Exception(f"MCP get_gmb failed: {r2.status_code}")

        data = _parse_sse(r2.content.decode("utf-8"))

        if data.get("error"):
            raise Exception(f"MCP error: {data['error']}")

        # Extract record from MCP content wrapper
        content = data.get("result", {}).get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "")
            if text:
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    pass

        return None


def _parse_sse(text: str) -> dict:
    """Extract JSON from SSE 'data:' line or fall back to direct JSON parse."""
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except (json.JSONDecodeError, ValueError):
                pass
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"raw": text[:300]}


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------

def do_check_customer(api_key: str, inp: dict) -> dict:
    place_id = inp.get("place_id", "").strip()
    if not place_id:
        return {"error": "place_id is required"}

    # Step 1: resolve place_id → email via Retool DB
    email = inp.get("email", "").strip() or get_email_by_place_id(place_id)

    if not email:
        # Not in Retool DB — definitely a new lead
        return {"status": "new_lead"}

    # Step 2: look up in Xano by email
    try:
        record = xano_get_gmb(api_key, email)
    except Exception as e:
        return {"error": str(e)}

    if not record:
        return {"status": "new_lead"}

    # Step 3: nonPayingClient = false → active paying customer
    #         nonPayingClient = true  → previously had account, now canceled
    non_paying = record.get("nonPayingClient", True)

    if not non_paying:
        return {
            "status": "active_customer",
            "action": "closed",
            "message": LOGIN_LINK_MESSAGE,
        }

    return {
        "status": "expired_customer",
        "action": "closed",
        "message": REACTIVATION_LINK_MESSAGE,
    }


try:
    api_key = os.environ.get("XANO_MCP_API_KEY", "").strip()
    if not api_key:
        raise Exception("XANO_MCP_API_KEY environment variable is not set.")

    inp = json.loads(os.environ.get("INPUT_JSON", "{}"))
    action = inp.get("action", "check_customer")

    if action == "check_customer":
        result = do_check_customer(api_key, inp)
    else:
        result = {"error": f"Unknown action '{action}'. Available actions: check_customer"}

    print(json.dumps(result, ensure_ascii=True))

except Exception as e:
    print(json.dumps({"error": str(e)}, ensure_ascii=True))
