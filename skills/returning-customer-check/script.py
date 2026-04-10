import os
import json
import httpx
import psycopg2
import psycopg2.extras

def _out(data: dict):
    """Write JSON output directly to stdout fd — safe in ASCII-only oya sandbox."""
    try:
        s = json.dumps(data, ensure_ascii=True, default=str)
        os.write(1, (s + "\n").encode("ascii", errors="replace"))
    except Exception:
        def _sanitize(obj):
            if isinstance(obj, str):
                return obj.encode("ascii", errors="replace").decode("ascii")
            if isinstance(obj, dict):
                return {_sanitize(k): _sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_sanitize(i) for i in obj]
            return obj
        try:
            s = json.dumps(_sanitize(data), default=str)
            os.write(1, (s + "\n").encode("ascii", errors="replace"))
        except Exception:
            os.write(1, b'{"error": "output_failed"}\n')

XANO_MCP_STREAM = "https://xktx-zdsw-4yq2.n7.xano.io/x2/mcp/hEfoWGi_/mcp/stream"
RETOOL_DB_URL = os.environ.get(
    "RETOOL_DB_URL",
    "postgresql://retool:npg_H0EaIfvzmg3Q@ep-small-surf-a6occgdz-pooler.us-west-2"
    ".retooldb.com/retool?sslmode=require",
)

LOGIN_LINK_MESSAGE = (
    "It looks like your business already has an active Jumper Local account! "
    "You can sign in here: https://local.jumpermedia.co/signin\n\n"
    "If you need any help, feel free to reach out to our support team."
)

REACTIVATION_LINK_MESSAGE = (
    "Welcome back! It looks like your business previously had a Jumper Local account, "
    "but your plan is no longer active.\n\n"
    "To reactivate your GMB and get your Google rankings back on track, you can schedule "
    "a call with our team here: https://calendly.com/jmpsales/google-ranking-increase-jumper-local\n\n"
    "We'd love to help you get started again!"
)

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_CLIENT_NAME = "returning-customer-check"
MCP_CLIENT_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Retool DB — resolve place_id → email
# ---------------------------------------------------------------------------

def get_email_from_retool(place_id: str = None, address: str = None, name: str = None) -> str | None:
    """
    Look up customer email in Retool DB.
    Priority: place_id → address → business name.
    """
    try:
        conn = psycopg2.connect(RETOOL_DB_URL, connect_timeout=15)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if place_id:
                    cur.execute(
                        "SELECT email FROM backfill_gmbs_names_and_other "
                        "WHERE place_id = %s AND email IS NOT NULL LIMIT 1",
                        (place_id,),
                    )
                    row = cur.fetchone()
                    if row:
                        return row["email"]
                if address:
                    cur.execute(
                        "SELECT email FROM backfill_gmbs_names_and_other "
                        "WHERE address ILIKE %s AND email IS NOT NULL LIMIT 1",
                        (f"%{address.strip()}%",),
                    )
                    row = cur.fetchone()
                    if row:
                        return row["email"]
                if name:
                    cur.execute(
                        "SELECT email FROM backfill_gmbs_names_and_other "
                        "WHERE business_name ILIKE %s AND email IS NOT NULL LIMIT 1",
                        (f"%{name.strip()}%",),
                    )
                    row = cur.fetchone()
                    if row:
                        return row["email"]
        finally:
            conn.close()
    except Exception:
        return None
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
    address = (inp.get("formatted_address") or inp.get("address") or "").strip()
    name = (inp.get("name") or inp.get("business_name") or "").strip()

    if not place_id and not address and not name:
        return {"error": "Provide at least one of: place_id, formatted_address, name"}

    # Step 1: resolve email via Retool DB — place_id → address → name
    email = inp.get("email", "").strip() or get_email_from_retool(
        place_id=place_id or None,
        address=address or None,
        name=name or None,
    )

    if not email:
        # Not in Retool DB — treat as new lead
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

    _out(result)

except Exception as e:
    _out({"error": str(e)})
