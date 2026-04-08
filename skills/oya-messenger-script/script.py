import os
import sys
import io
import json
import uuid
import httpx
import psycopg2
import psycopg2.extras

# Force UTF-8 stdout — oya sandbox defaults to ASCII
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

print(f"A2ABASEAI_FILE: script.py")

ONBOARDING_URL = "https://local.jumpermedia.co/onboarding/utm=oya"
CALENDLY_URL = "https://calendly.com/jmpsales/google-ranking-increase-jumper-local"
PLACES_BASE = "https://maps.googleapis.com/maps/api/place"
RETOOL_DB_URL = os.environ.get(
    "RETOOL_DB_URL",
    "postgresql://retool:npg_H0EaIfvzmg3Q@ep-small-surf-a6occgdz-pooler.us-west-2"
    ".retooldb.com/retool?sslmode=require",
)
MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_CLIENT_NAME = "oya-messenger-script"
MCP_CLIENT_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Session management (Retool DB)
# ---------------------------------------------------------------------------

def db_exec(sql, params=()):
    conn = psycopg2.connect(RETOOL_DB_URL, connect_timeout=20)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            conn.commit()
            try:
                return [dict(r) for r in cur.fetchall()]
            except Exception:
                return []
    finally:
        conn.close()


def get_session(sender_id):
    rows = db_exec(
        "SELECT * FROM oya_messenger_sessions WHERE sender_id = %s LIMIT 1",
        (sender_id,),
    )
    return dict(rows[0]) if rows else None


def upsert_session(sender_id, fields: dict):
    fields["sender_id"] = sender_id
    cols = ", ".join(fields.keys()) + ", created_at, updated_at"
    vals = ", ".join(["%s"] * len(fields)) + ", NOW(), NOW()"
    updates = ", ".join([f"{k} = EXCLUDED.{k}" for k in fields.keys() if k != "sender_id"])
    db_exec(
        f"INSERT INTO oya_messenger_sessions ({cols}) VALUES ({vals}) "
        f"ON CONFLICT (sender_id) DO UPDATE SET {updates}, updated_at = NOW()",
        list(fields.values()),
    )
    return get_session(sender_id)


def delete_session(sender_id):
    db_exec("DELETE FROM oya_messenger_sessions WHERE sender_id = %s", (sender_id,))


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def api_get(url, params=None, timeout=20):
    with httpx.Client(timeout=timeout) as c:
        r = c.get(url, params=params or {})
        if r.status_code >= 400:
            raise Exception(f"HTTP {r.status_code}: {r.text[:400]}")
        return r.json()


# ---------------------------------------------------------------------------
# Xano MCP helpers — initialize + tool call in one session
# ---------------------------------------------------------------------------

def mcp_call_tool(stream_url, tool_name, arguments, timeout=30):
    """
    Performs MCP initialize handshake + tool call in one persistent httpx.Client
    so the server sees a single session. Avoids 'Server not initialized' errors.
    """
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": MCP_CLIENT_NAME, "version": MCP_CLIENT_VERSION},
        },
    }
    notif_payload = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    }
    tool_payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }

    with httpx.Client(timeout=timeout) as c:
        r = c.post(stream_url, headers=headers, json=init_payload)
        if r.status_code >= 400:
            raise Exception(f"MCP initialize error {r.status_code}: {r.content.decode('utf-8', errors='replace')[:400]}")

        c.post(stream_url, headers=headers, json=notif_payload)

        r2 = c.post(stream_url, headers=headers, json=tool_payload)
        if r2.status_code >= 400:
            raise Exception(f"MCP tool call error {r2.status_code}: {r2.content.decode('utf-8', errors='replace')[:400]}")

        data = json.loads(r2.content.decode("utf-8"))

    error = data.get("error")
    if error:
        raise Exception(f"MCP error: {error}")

    result = data.get("result", {})
    content = result.get("content", [])
    if content and isinstance(content, list):
        first = content[0]
        if isinstance(first, dict) and "text" in first:
            try:
                return json.loads(first["text"])
            except (json.JSONDecodeError, TypeError):
                return first["text"]
        return first
    return result


def xano_mcp_get(stream_url, tool_name, arguments, timeout=15):
    """
    Wrapper for read-style MCP tool calls. Returns None if result indicates
    not found, otherwise returns the result data.
    """
    try:
        result = mcp_call_tool(stream_url, tool_name, arguments, timeout=timeout)
    except Exception as e:
        msg = str(e).lower()
        if "not found" in msg or "404" in msg:
            return None
        raise
    if result is None:
        return None
    if isinstance(result, dict) and result.get("status") == "not_found":
        return None
    return result


def xano_mcp_post(stream_url, tool_name, arguments, timeout=20):
    """
    Wrapper for write-style MCP tool calls.
    """
    return mcp_call_tool(stream_url, tool_name, arguments, timeout=timeout)


# ---------------------------------------------------------------------------
# Google Places helpers
# ---------------------------------------------------------------------------

def places_text_search(api_key, query, timeout=20):
    data = api_get(
        f"{PLACES_BASE}/textsearch/json",
        params={"query": query, "key": api_key},
        timeout=timeout,
    )
    status = data.get("status", "")
    if status not in ("OK", "ZERO_RESULTS"):
        raise Exception(f"Places API error: {status} — {data.get('error_message', '')}")
    # Cap at 3 results — Text Search can return up to 20, no need to pass all to LLM
    return data.get("results", [])[:3]


def places_details(api_key, place_id, timeout=20):
    """Fetch website and full opening hours — not returned by Text Search."""
    data = api_get(
        f"{PLACES_BASE}/details/json",
        params={
            "place_id": place_id,
            "fields": "website,opening_hours",
            "key": api_key,
        },
        timeout=timeout,
    )
    if data.get("status") != "OK":
        return {}
    return data.get("result", {})


def extract_place_summary(place):
    # opening_hours key present = hours configured on the listing (periods may still be empty for 24/7)
    has_hours = "opening_hours" in place
    return {
        "place_id": place.get("place_id", ""),
        "name": place.get("name", ""),
        "address": place.get("formatted_address", ""),
        "rating": place.get("rating"),
        "user_ratings_total": place.get("user_ratings_total", 0),
        "has_hours": has_hours,
        "website": place.get("website", ""),  # populated only after Place Details call
        "types": place.get("types", []),
    }


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def do_reset_session(inp):
    """
    Called on MAPS trigger or any new conversation start.
    Clears all stored session state so the agent starts completely fresh.
    """
    sender_id = (inp.get("sender_id") or "").strip()
    if sender_id:
        delete_session(sender_id)
    return {"status": "session_cleared", "message": ""}


def do_trigger_welcome(inp):
    sender_id = (inp.get("sender_id") or "").strip()
    first_name = (inp.get("lead_first_name") or "").strip()

    # Always reset session on welcome trigger
    if sender_id:
        delete_session(sender_id)
        upsert_session(sender_id, {"step": "awaiting_gmb_name"})

    if first_name:
        msg = (
            f"Hey {first_name}! I'm Hannah 👋 "
            "Give me your business name. Going to look you up to see if we can help"
        )
    else:
        msg = (
            "Hey! I'm Hannah 👋 "
            "Give me your business name. Going to look you up to see if we can help"
        )
    return {"message": msg}


def do_gmb_lookup(inp, places_key):
    raw = (inp.get("gmb_name_raw") or "").strip()
    if not raw:
        return {"error": "Provide gmb_name_raw — the assembled business name from the lead"}

    # Special case: lead says their GMB is Jumper Media
    if raw.lower() in ("jumper media", "jumpermedia"):
        return {
            "status": "jumper_media",
            "message": "Hey, that's us! What is your GMB name? 😄",
            "results": [],
        }

    address_hint = (inp.get("gmb_address_hint") or "").strip()
    query = f"{raw} {address_hint}".strip()
    sender_id = (inp.get("sender_id") or "").strip()

    results_raw = places_text_search(places_key, query)
    results = [extract_place_summary(p) for p in results_raw]

    if len(results) == 0:
        return {
            "status": "no_results",
            "message": (
                "Hmm, I wasn't able to find that listing on Google. "
                "Could you double-check the name? It should appear exactly as it does "
                "when you search your business on Google Maps."
            ),
            "results": [],
        }

    if len(results) == 1:
        r = results[0]
        # Fetch Place Details to get website and accurate hours for qualification
        details = places_details(places_key, r["place_id"])
        r["website"] = details.get("website", "")
        r["has_hours"] = "opening_hours" in details or r["has_hours"]

        # Save to session so we don't rely on LLM memory
        if sender_id:
            upsert_session(sender_id, {
                "step": "awaiting_confirmation",
                "gmb_name": r["name"],
                "gmb_address": r["address"],
                "place_id": r["place_id"],
            })

        return {
            "status": "one_result",
            "message": (
                f"I found this listing — is this yours?\n\n"
                f"📍 {r['name']}\n{r['address']}"
            ),
            "results": [r],
        }

    # Multiple results — ask for address to narrow down
    return {
        "status": "multiple_results",
        "message": (
            "I found a few businesses with that name. "
            "Can you share your business address so I can find the right one?"
        ),
        "results": results,
    }


def do_check_xano_gmb(inp, stream_url, login_link):
    place_id = (inp.get("place_id") or "").strip()
    if not place_id:
        return {"error": "Provide place_id to check Xano"}

    data = xano_mcp_get(stream_url, "gmb_lookup", {"place_id": place_id})

    if not data:
        return {"status": "not_found", "message": ""}

    # Determine active subscription / trial
    has_active = bool(data.get("active_subscription") or data.get("active_trial"))

    if has_active:
        msg = (
            "It looks like your business already has an active account with us! "
            f"You can log in here: {login_link}. "
            "If you need help, feel free to reach out to our support team. 😊"
        )
        return {"status": "current_customer", "message": msg}

    return {"status": "returning_customer", "message": ""}


def do_check_xano_email(inp, stream_url, login_link):
    email = (inp.get("lead_email") or "").strip()
    if not email:
        return {"error": "Provide lead_email to check Xano"}

    data = xano_mcp_get(stream_url, "email_lookup", {"email": email})

    if not data:
        return {"status": "not_found", "message": ""}

    has_active = bool(data.get("active_subscription") or data.get("active_trial"))

    if has_active:
        msg = (
            "It looks like you already have an active Jumper Local account! "
            f"Log in here: {login_link}. "
            "Need help? Contact our support team. 😊"
        )
        return {"status": "current_customer", "message": msg}

    return {"status": "returning_customer", "message": ""}


def do_submit_onboarding_form(inp, stream_url):
    required = ["confirmed_gmb_name", "confirmed_gmb_address", "place_id",
                "lead_full_name", "lead_email", "lead_phone"]
    missing = [f for f in required if not (inp.get(f) or "").strip()]
    if missing:
        return {"error": f"Missing required fields: {', '.join(missing)}"}

    arguments = {
        "gmb_name": inp["confirmed_gmb_name"].strip(),
        "gmb_address": inp["confirmed_gmb_address"].strip(),
        "place_id": inp["place_id"].strip(),
        "full_name": inp["lead_full_name"].strip(),
        "email": inp["lead_email"].strip(),
        "phone": inp["lead_phone"].strip(),
        "source": "oya",
        "onboarding_url": ONBOARDING_URL,
    }

    result = xano_mcp_post(stream_url, "onboarding_submit", arguments)

    if isinstance(result, dict):
        submission_id = result.get("id") or result.get("submission_id") or "N/A"
    else:
        submission_id = "N/A"

    return {
        "status": "submitted",
        "submission_id": submission_id,
        "message": (
            "Awesome! Your free trial of Jumper Local has been initiated. "
            "You should see improved rankings in less than a week. "
            "The last step is to schedule with a specialist to go over your results. "
            f"Choose a time that works best for you here: {CALENDLY_URL}"
        ),
    }


def do_close_conversation():
    return {
        "message": (
            "Awesome! Your free trial of Jumper Local has been initiated. "
            "You should see improved rankings in less than a week. "
            "The last step is to schedule with a specialist to go over your results. "
            f"Choose a time that works best for you here: {CALENDLY_URL}"
        )
    }


def do_redirect_offtopic():
    return {
        "message": "Great question! Let's get your onboarding sorted first — we can cover that after. 😊"
    }


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

try:
    inp = json.loads(os.environ.get("INPUT_JSON", "{}"))
    action = (inp.get("action") or "").strip()

    places_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    stream_url = (
        os.environ.get("XANO_MCP_STREAM_URL")
        or "https://xktx-zdsw-4yq2.n7.xano.io/x2/mcp/hEfoWGi_/mcp/stream"
    ).rstrip("/")
    login_link = os.environ.get(
        "ONBOARDING_LOGIN_LINK", "https://local.jumpermedia.co/login"
    )

    if action == "reset_session":
        result = do_reset_session(inp)

    elif action == "trigger_welcome":
        result = do_trigger_welcome(inp)

    elif action == "gmb_lookup":
        if not places_key:
            result = {"error": "GOOGLE_PLACES_API_KEY env var is not set"}
        else:
            result = do_gmb_lookup(inp, places_key)

    elif action == "get_session":
        sender_id = (inp.get("sender_id") or "").strip()
        result = get_session(sender_id) or {"status": "no_session"}

    elif action == "check_xano_gmb":
        result = do_check_xano_gmb(inp, stream_url, login_link)

    elif action == "check_xano_email":
        result = do_check_xano_email(inp, stream_url, login_link)

    elif action == "submit_onboarding_form":
        result = do_submit_onboarding_form(inp, stream_url)

    elif action == "close_conversation":
        result = do_close_conversation()

    elif action == "redirect_offtopic":
        result = do_redirect_offtopic()

    else:
        result = {
            "error": (
                f"Unknown action: '{action}'. "
                "Valid actions: reset_session, trigger_welcome, gmb_lookup, get_session, "
                "check_xano_gmb, check_xano_email, submit_onboarding_form, "
                "close_conversation, redirect_offtopic"
            )
        }

    print(json.dumps(result))

except Exception as e:
    print(json.dumps({"error": str(e)}))