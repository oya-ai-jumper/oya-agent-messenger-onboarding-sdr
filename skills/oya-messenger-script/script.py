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

def mcp_call_tool(stream_url, tool_name, arguments, api_key=None, timeout=30):
    """
    Performs MCP initialize handshake + tool call in one persistent httpx.Client
    so the server sees a single session. Avoids 'Server not initialized' errors.
    """
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if api_key:
        headers["Authorization"] = api_key

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

        # Extract mcp-session-id — Xano returns it as a response header.
        # Try all known header name variations (Xano has used different casings).
        session_id = (
            r.headers.get("mcp-session-id")
            or r.headers.get("x-mcp-session-id")
            or r.headers.get("session-id")
            or ""
        )
        if not session_id:
            # Fallback: parse from SSE body in case Xano embeds it there
            for line in r.content.decode("utf-8", errors="replace").splitlines():
                if line.startswith("data:"):
                    try:
                        body = json.loads(line[5:].strip())
                        session_id = (
                            body.get("sessionId")
                            or body.get("session_id")
                            or body.get("result", {}).get("sessionId", "")
                        )
                        if session_id:
                            break
                    except (json.JSONDecodeError, ValueError):
                        pass

        # Only add the header if we have a non-empty session ID.
        # Passing an empty mcp-session-id causes Xano to return 400 "Server not initialized".
        session_headers = {**headers}
        if session_id:
            session_headers["mcp-session-id"] = session_id

        rn = c.post(stream_url, headers=session_headers, json=notif_payload)
        # notifications/initialized may return 200 or 202 — both are valid
        if rn.status_code >= 400:
            raise Exception(f"MCP notifications/initialized error {rn.status_code}: {rn.content.decode('utf-8', errors='replace')[:200]}")

        r2 = c.post(stream_url, headers=session_headers, json=tool_payload)
        if r2.status_code >= 400:
            raise Exception(f"MCP tool call error {r2.status_code}: {r2.content.decode('utf-8', errors='replace')[:400]}")

        raw = r2.content.decode("utf-8")
        # Xano returns SSE format: "event: message\ndata: {...}"
        data = None
        for line in raw.splitlines():
            if line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                    break
                except (json.JSONDecodeError, ValueError):
                    pass
        if data is None:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                data = {}

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


def xano_mcp_get(stream_url, tool_name, arguments, api_key=None, timeout=15):
    """
    Wrapper for read-style MCP tool calls. Returns None if result indicates
    not found, otherwise returns the result data.
    """
    try:
        result = mcp_call_tool(stream_url, tool_name, arguments, api_key=api_key, timeout=timeout)
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


def xano_mcp_post(stream_url, tool_name, arguments, api_key=None, timeout=20):
    """
    Wrapper for write-style MCP tool calls.
    """
    return mcp_call_tool(stream_url, tool_name, arguments, api_key=api_key, timeout=timeout)


def list_mcp_tools(stream_url, api_key=None, timeout=20):
    """Return list of tool names registered on the Xano MCP server."""
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if api_key:
        headers["Authorization"] = api_key

    init_payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {},
                               "clientInfo": {"name": MCP_CLIENT_NAME, "version": MCP_CLIENT_VERSION}}}
    list_payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}

    with httpx.Client(timeout=timeout) as c:
        r = c.post(stream_url, headers=headers, json=init_payload)
        session_id = r.headers.get("mcp-session-id") or r.headers.get("x-mcp-session-id") or ""
        if session_id:
            headers["mcp-session-id"] = session_id
        c.post(stream_url, headers=headers,
               json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        r2 = c.post(stream_url, headers=headers, json=list_payload)

    raw = r2.content.decode("utf-8", errors="replace")
    for line in raw.splitlines():
        if line.startswith("data:"):
            try:
                data = json.loads(line[5:].strip())
                tools = data.get("result", {}).get("tools", [])
                return [t.get("name") for t in tools]
            except Exception:
                pass
    try:
        data = json.loads(raw)
        tools = data.get("result", {}).get("tools", [])
        return [t.get("name") for t in tools]
    except Exception:
        return {"raw_response": raw[:500]}


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


def places_full_qualification(api_key, place_id, timeout=20):
    """Fetch all four qualification fields in one call for recheck use."""
    data = api_get(
        f"{PLACES_BASE}/details/json",
        params={
            "place_id": place_id,
            "fields": "website,opening_hours,rating,user_ratings_total",
            "key": api_key,
        },
        timeout=timeout,
    )
    if data.get("status") != "OK":
        return None
    result = data.get("result", {})
    return {
        "has_hours":          "opening_hours" in result,
        "website":            result.get("website", ""),
        "rating":             result.get("rating") or 0,
        "user_ratings_total": result.get("user_ratings_total", 0),
    }


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

def do_confirm_gmb(inp):
    """
    Called after the lead confirms their GMB listing.
    Saves the confirmed place_id, name, and address to the session so they
    can be reliably used in subsequent checks (returning customer, qualification).
    """
    sender_id = (inp.get("sender_id") or "").strip()
    place_id = (inp.get("place_id") or "").strip()
    name = (inp.get("confirmed_gmb_name") or inp.get("name") or "").strip()
    address = (inp.get("confirmed_gmb_address") or inp.get("address") or "").strip()

    # If place_id is missing, look it up from Retool DB by address then name
    if not place_id and (address or name):
        try:
            conn = psycopg2.connect(RETOOL_DB_URL, connect_timeout=15)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    if address:
                        cur.execute(
                            "SELECT place_id FROM backfill_gmbs_names_and_other "
                            "WHERE address ILIKE %s LIMIT 1",
                            (f"%{address}%",),
                        )
                        row = cur.fetchone()
                        if row:
                            place_id = row["place_id"]
                    if not place_id and name:
                        cur.execute(
                            "SELECT place_id FROM backfill_gmbs_names_and_other "
                            "WHERE business_name ILIKE %s LIMIT 1",
                            (f"%{name}%",),
                        )
                        row = cur.fetchone()
                        if row:
                            place_id = row["place_id"]
            finally:
                conn.close()
        except Exception:
            pass

    if not place_id:
        return {"error": "place_id is required — pass it directly or ensure the business is in the Retool DB"}

    if sender_id:
        upsert_session(sender_id, {
            "step": "gmb_confirmed",
            "place_id": place_id,
            "gmb_name": name,
            "gmb_address": address,
        })

    return {
        "status": "confirmed",
        "place_id": place_id,
        "confirmed_gmb_name": name,
        "confirmed_gmb_address": address,
    }


def do_reset_session(inp):
    """
    Called on MAPS trigger or any new conversation start.
    Clears all stored session state so the agent starts completely fresh.
    """
    sender_id = (inp.get("sender_id") or "").strip()
    if sender_id:
        delete_session(sender_id)
    return {"status": "session_cleared", "message": ""}


_FB_TOKEN_FALLBACK = "EAANG25a4eFgBRGn7kYQYQ3YOru4IKZANCMlzzQfJRFEewAW4iNZAo6ZBvo0S1f0juyPPdoz7rgT8skHMt0xjnZBHExW2dHZAkzbnZCtjWdYKZA3QgdFywsCPrnBUHEmuECa6ZAHUFDSugmR2vHY1UawIzKDXKWyS2J8MlcYQ9DkeRqJjAKIgKT7kPekwHrD1YCUwZCNB8EwZDZD"

def get_fb_first_name(sender_id: str) -> str:
    """
    Fetch the sender's first name from the Facebook Graph API.
    Checks env vars first, falls back to hardcoded token.
    Returns empty string if unavailable.
    """
    token = (
        os.environ.get("FB_PAGE_ACCESS_TOKEN")
        or os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN")
        or os.environ.get("PAGE_ACCESS_TOKEN")
        or _FB_TOKEN_FALLBACK
    ).strip()
    if not token or not sender_id:
        return ""
    try:
        url = f"https://graph.facebook.com/v19.0/{sender_id}"
        with httpx.Client(timeout=5) as c:
            r = c.get(url, params={"fields": "first_name", "access_token": token})
            if r.status_code == 200:
                name = r.json().get("first_name", "").strip()
                print(f"[get_fb_first_name] sender={sender_id} name={name!r}", flush=True)
                return name
            else:
                print(f"[get_fb_first_name] API error {r.status_code}: {r.text[:300]}", flush=True)
    except Exception as e:
        print(f"[get_fb_first_name] Exception: {e}", flush=True)
    return ""


def do_trigger_welcome(inp):
    sender_id = (inp.get("sender_id") or "").strip()
    # Accept name passed directly, fall back to Graph API lookup
    first_name = (inp.get("lead_first_name") or "").strip()
    if not first_name and sender_id:
        first_name = get_fb_first_name(sender_id)

    # Always reset session on welcome trigger
    if sender_id:
        delete_session(sender_id)
        upsert_session(sender_id, {"step": "awaiting_gmb_name"})

    name = first_name if first_name else "there"
    msg = (
        f"Hey {name}! I'm Hannah 👋 "
        "Give me your business name. Going to look you up to see if we can help"
    )
    return {"message": msg, "lead_first_name": first_name}


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
            "message": "Sorry! Couldn't find your profile. What's your business address?",
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
            # Approved script: show listing details then ask "Is this your business?"
            "message": f"📍 {r['name']}\n{r['address']}\n\nIs this your business?",
            "results": [r],
        }

    # Multiple results — ask for address to narrow down
    return {
        "status": "multiple_results",
        "message": "Sorry! Couldn't find your profile. What's your business address?",
        "results": results,
    }


def _retool_lookup(place_id=None, address=None, business_name=None):
    """
    Look up email from backfill_gmbs_names_and_other.
    Priority: place_id → address → business_name.
    Returns email string or None.
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
                if business_name:
                    cur.execute(
                        "SELECT email FROM backfill_gmbs_names_and_other "
                        "WHERE business_name ILIKE %s AND email IS NOT NULL LIMIT 1",
                        (f"%{business_name.strip()}%",),
                    )
                    row = cur.fetchone()
                    if row:
                        return row["email"]
        finally:
            conn.close()
    except Exception:
        pass
    return None


def do_check_xano_gmb(inp, stream_url, login_link, api_key=None):
    # Priority for place_id:
    # 1. Session (saved by confirm_gmb) — most reliable
    # 2. Input place_id from LLM
    # 3. Fall back to address/name lookup in Retool DB
    sender_id = (inp.get("sender_id") or "").strip()
    place_id = ""
    if sender_id:
        session = get_session(sender_id)
        if session and session.get("place_id"):
            place_id = session["place_id"]

    if not place_id:
        place_id = (inp.get("place_id") or "").strip()

    email = (inp.get("email") or "").strip()
    address = (inp.get("confirmed_gmb_address") or inp.get("address") or "").strip()
    business_name = (inp.get("confirmed_gmb_name") or inp.get("name") or "").strip()

    if not place_id and not email and not address and not business_name:
        return {"error": "Provide sender_id, place_id, email, confirmed_gmb_address, or confirmed_gmb_name"}

    # Resolve email via Retool DB — try place_id, then address, then name
    if not email:
        email = _retool_lookup(
            place_id=place_id or None,
            address=address or None,
            business_name=business_name or None,
        )

    if not email:
        return {"status": "new_lead", "next_step": "run gmb-qualification-check with action=recheck and place_id"}

    # Use get_gmb tool — the only valid Xano lookup tool
    data = xano_mcp_get(stream_url, "get_gmb", {"email": email}, api_key=api_key)

    if not data:
        return {"status": "new_lead", "next_step": "run gmb-qualification-check with action=recheck and place_id"}

    # nonPayingClient=false → active paying customer
    # nonPayingClient=true  → previously had account, now canceled
    non_paying = data.get("nonPayingClient", True)

    if not non_paying:
        msg = (
            "It looks like your business already has an active Jumper Local account! "
            f"You can sign in here: {login_link}\n\n"
            "If you need any help, feel free to reach out to our support team."
        )
        return {"status": "active_customer", "message": msg}

    msg = (
        "Welcome back! It looks like your business previously had a Jumper Local account, "
        "but your plan is no longer active.\n\n"
        "To reactivate your GMB and get your Google rankings back on track, you can schedule "
        "a call with our team here: https://calendly.com/jmpsales/google-ranking-increase-jumper-local\n\n"
        "We'd love to help you get started again!"
    )
    return {"status": "expired_customer", "message": msg}


def do_check_xano_email(inp, stream_url, login_link, api_key=None):
    email = (inp.get("lead_email") or "").strip()
    if not email:
        return {"error": "Provide lead_email to check Xano"}

    data = xano_mcp_get(stream_url, "email_lookup", {"email": email}, api_key=api_key)

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


def _ensure_onboarding_leads_table():
    db_exec("""
        CREATE TABLE IF NOT EXISTS oya_onboarding_leads (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            sender_id TEXT,
            gmb_name TEXT,
            gmb_address TEXT,
            place_id TEXT,
            full_name TEXT,
            email TEXT,
            phone TEXT,
            keywords TEXT,
            source TEXT DEFAULT 'oya_messenger',
            tags TEXT DEFAULT 'CHAT LEAD DO NOT CALL',
            status TEXT DEFAULT 'pending'
        )
    """)


def _slack_notify_lead(lead: dict, slack_token: str):
    """Post a lead notification to the Jumper Local Slack channel."""
    kw_str = ", ".join(lead.get("keywords") or []) or "—"
    text = (
        f":bell: *New Oya Chat Lead — Action Required*\n"
        f"*Business:* {lead['gmb_name']}\n"
        f"*Address:* {lead['gmb_address']}\n"
        f"*Place ID:* `{lead['place_id']}`\n"
        f"*Name:* {lead['full_name']}\n"
        f"*Email:* {lead['email']}\n"
        f"*Phone:* {lead['phone']}\n"
        f"*Keywords:* {kw_str}\n"
        f"*Source:* oya_messenger  •  *Tag:* CHAT LEAD DO NOT CALL\n"
        f"Please create their Jumper Local account: {ONBOARDING_URL}"
    )
    try:
        httpx.post(
            "https://slack.com/api/chat.postMessage",
            json={"channel": "jumper-local-tech-support", "text": text},
            headers={"Authorization": f"Bearer {slack_token}"},
            timeout=10,
        )
    except Exception:
        pass  # Notification failure must not block the submission response


def do_submit_onboarding_form(inp, stream_url=None, api_key=None):
    required = ["confirmed_gmb_name", "confirmed_gmb_address", "place_id",
                "lead_full_name", "lead_email", "lead_phone"]
    missing = [f for f in required if not (inp.get(f) or "").strip()]
    if missing:
        return {"error": f"Missing required fields: {', '.join(missing)}"}

    sender_id = (inp.get("sender_id") or "").strip()
    keywords = []
    if sender_id:
        session = get_session(sender_id)
        if session and session.get("keywords"):
            try:
                keywords = json.loads(session["keywords"])
            except (json.JSONDecodeError, TypeError):
                keywords = []
    if not keywords and inp.get("keywords"):
        kw = inp["keywords"]
        keywords = kw if isinstance(kw, list) else [k.strip() for k in kw.split(",") if k.strip()]

    lead = {
        "gmb_name":    inp["confirmed_gmb_name"].strip(),
        "gmb_address": inp["confirmed_gmb_address"].strip(),
        "place_id":    inp["place_id"].strip(),
        "full_name":   inp["lead_full_name"].strip(),
        "email":       inp["lead_email"].strip(),
        "phone":       inp["lead_phone"].strip(),
        "keywords":    keywords,
    }

    # Save to Retool DB
    _ensure_onboarding_leads_table()
    db_exec(
        """
        INSERT INTO oya_onboarding_leads
            (sender_id, gmb_name, gmb_address, place_id, full_name, email, phone, keywords)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            sender_id,
            lead["gmb_name"], lead["gmb_address"], lead["place_id"],
            lead["full_name"], lead["email"], lead["phone"],
            json.dumps(keywords),
        ),
    )

    # Mark session as onboarding_submitted
    if sender_id:
        upsert_session(sender_id, {"step": "onboarding_submitted"})

    # Slack notification
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if slack_token:
        _slack_notify_lead(lead, slack_token)

    return {
        "status": "submitted",
        "message": (
            "Awesome! Your free trial of Jumper Local has been initiated. "
            "You should see improved rankings in less than a week. "
            "The last step is to schedule with a specialist to go over your results. "
            f"Choose a time that works best for you here: {CALENDLY_URL}"
        ),
    }


def do_save_keywords(inp):
    """
    Called after the lead confirms their 3 target keywords.
    Saves keywords to session so they are included in the onboarding form submission.
    """
    sender_id = (inp.get("sender_id") or "").strip()
    keywords = inp.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    if not keywords:
        return {"error": "Provide keywords as a list or comma-separated string"}
    if sender_id:
        upsert_session(sender_id, {"keywords": json.dumps(keywords), "step": "keywords_confirmed"})
    return {"status": "saved", "keywords": keywords}


def do_post_booking():
    """
    Called after the lead confirms their Calendly booking.
    Returns the final confirmation message with CEO video link.
    """
    return {
        "message": (
            "You're booked! Before I let you go, here's a quick video from our CEO. "
            "We'll see you soon!"
        )
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


_DISQUALIFICATION_REASONS = ("no_hours", "no_website", "low_reviews", "low_rating")


def do_save_disqualification(inp):
    """
    Called immediately after Oya delivers a disqualification message.
    Stores the reason in the session step so recheck_qualification can
    re-run the right criteria when the lead returns.
    Step format: "disqualified_<reason>"  e.g. "disqualified_no_hours"
    """
    sender_id = (inp.get("sender_id") or "").strip()
    reason    = (inp.get("reason") or "").strip()

    if not sender_id:
        return {"error": "sender_id required"}
    if reason not in _DISQUALIFICATION_REASONS:
        return {"error": f"reason must be one of: {', '.join(_DISQUALIFICATION_REASONS)}"}

    upsert_session(sender_id, {"step": f"disqualified_{reason}"})
    return {"status": "saved", "step": f"disqualified_{reason}"}


def do_recheck_qualification(inp, places_key):
    """
    Called when a previously disqualified lead returns claiming they fixed the issue.
    Reads place_id and disqualification reason from session, re-fetches live Google
    Places data, and re-checks only the criterion that failed.

    Returns:
      result=qualified        → continue onboarding (also runs full check in case
                                other criteria regressed)
      result=still_disqualified → inform lead, session step unchanged
    """
    sender_id = (inp.get("sender_id") or "").strip()
    if not sender_id:
        return {"error": "sender_id required"}

    session = get_session(sender_id)
    if not session:
        return {"error": "no session found for this sender"}

    step = (session.get("step") or "").strip()
    reason_map = {
        f"disqualified_{r}": r for r in _DISQUALIFICATION_REASONS
    }
    reason = reason_map.get(step)
    if not reason:
        return {"error": f"lead is not in a disqualified state (current step: {step!r})"}

    place_id = (session.get("place_id") or "").strip()
    if not place_id:
        return {"error": "no place_id in session — ask the lead for their business name again"}

    if not places_key:
        return {"error": "GOOGLE_PLACES_API_KEY env var is not set"}

    try:
        qdata = places_full_qualification(places_key, place_id)
    except Exception as e:
        return {"error": f"Google Places API error: {e}"}

    if not qdata:
        return {"error": "Could not fetch Place Details — place_id may be stale, run gmb_lookup again"}

    # Run full qualification check so we catch any other issues
    fails = []
    if not qdata["has_hours"]:
        fails.append("no_hours")
    if not qdata["website"]:
        fails.append("no_website")
    if qdata["user_ratings_total"] < 10:
        fails.append("low_reviews")
    if qdata["rating"] <= 3.0:
        fails.append("low_rating")

    if not fails:
        upsert_session(sender_id, {"step": "gmb_confirmed"})
        return {
            "result": "qualified",
            "resolved": reason,
            "gmb_data": qdata,
            "next_step": "continue onboarding from step 5b — collect lead name, email, phone",
        }

    # Update session to the first remaining failure (in case original reason was fixed
    # but something else now fails)
    upsert_session(sender_id, {"step": f"disqualified_{fails[0]}"})
    return {
        "result": "still_disqualified",
        "original_reason": reason,
        "current_failures": fails,
        "gmb_data": qdata,
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
    _xano_default = "https://xktx-zdsw-4yq2.n7.xano.io/x2/mcp/hEfoWGi_/mcp/stream"
    stream_url = (
        os.environ.get("XANO_MCP_STREAM_URL")
        or os.environ.get("XANO_MCP_STREAM")
        or _xano_default
    ).rstrip("/")
    # Ensure absolute URL — fall back to default if env var is a relative path
    if not stream_url.startswith(("http://", "https://")):
        stream_url = _xano_default
    xano_api_key = os.environ.get("XANO_MCP_API_KEY", "").strip()
    login_link = os.environ.get(
        "ONBOARDING_LOGIN_LINK", "https://local.jumpermedia.co/login"
    )

    if action == "confirm_gmb":
        result = do_confirm_gmb(inp)

    elif action == "reset_session":
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

    elif action == "check_gate":
        # Returns allow/block based on trigger word (MAPS or RANK) or active session.
        # Called as Rule 0 — if block, agent must send nothing and stop.
        sender_id = (inp.get("sender_id") or "").strip()
        message_text = (inp.get("message_text") or "").strip().upper()
        is_trigger = message_text in ("MAPS", "RANK")
        session = get_session(sender_id) if sender_id else None
        step = (session.get("step") or "").strip() if session else ""
        is_active = step not in ("", "completed", "session_cleared")
        if is_trigger or is_active:
            result = {"gate": "allow", "reason": "trigger" if is_trigger else "active_session"}
        else:
            result = {"gate": "block", "reason": "no_trigger_no_session"}

    elif action == "check_xano_gmb":
        result = do_check_xano_gmb(inp, stream_url, login_link, xano_api_key)

    elif action == "check_xano_email":
        result = do_check_xano_email(inp, stream_url, login_link, xano_api_key)

    elif action == "list_mcp_tools":
        result = {"tools": list_mcp_tools(stream_url, api_key=xano_api_key)}

    elif action == "save_disqualification":
        result = do_save_disqualification(inp)

    elif action == "recheck_qualification":
        if not places_key:
            result = {"error": "GOOGLE_PLACES_API_KEY env var is not set"}
        else:
            result = do_recheck_qualification(inp, places_key)

    elif action == "submit_onboarding_form":
        result = do_submit_onboarding_form(inp, stream_url, xano_api_key)

    elif action == "save_keywords":
        result = do_save_keywords(inp)

    elif action == "post_booking":
        result = do_post_booking()

    elif action == "close_conversation":
        result = do_close_conversation()

    elif action == "redirect_offtopic":
        result = do_redirect_offtopic()

    else:
        result = {
            "error": (
                f"Unknown action: '{action}'. "
                "Valid actions: reset_session, trigger_welcome, gmb_lookup, confirm_gmb, check_gate, "
                "save_disqualification, recheck_qualification, "
                "submit_onboarding_form, save_keywords, post_booking, redirect_offtopic. "
                "NOTE: Lead info (name/email/phone) is collected via direct conversation — no skill call needed. "
                "Call submit_onboarding_form only after all three are collected."
            )
        }

    print(json.dumps(result, default=str))

except Exception as e:
    print(json.dumps({"error": str(e)}))