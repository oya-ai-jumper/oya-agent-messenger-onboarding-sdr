import os
import json
import re
import httpx
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta

# ── Environment ──────────────────────────────────────────────────────────────
FB_PAGE_ACCESS_TOKEN  = os.environ.get("FB_PAGE_ACCESS_TOKEN", "")
GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")
RETOOL_DB_URL         = os.environ.get(
    "RETOOL_DB_URL",
    "postgresql://retool:npg_H0EaIfvzmg3Q@ep-small-surf-a6occgdz-pooler.us-west-2.retooldb.com/retool?sslmode=require",
)
CALENDLY_AE_URL = os.environ.get(
    "CALENDLY_AE_URL",
    "https://calendly.com/jmpsales/1-on-google-jumper-local-trial-rr-checkin",
)
GRAPH_API          = "https://graph.facebook.com/v19.0/me/messages"
PLACES_SEARCH_URL  = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAIL_URL  = "https://maps.googleapis.com/maps/api/place/details/json"
MAX_MSG_LENGTH     = 2000

# ── Keyword map ───────────────────────────────────────────────────────────────
KEYWORD_MAP = {
    "plumber":             ["{service} near me", "emergency {service} {city}", "{service} repair {city}", "best {service} {city}", "drain cleaning {city}"],
    "electrician":         ["{service} near me", "emergency {service} {city}", "{service} services {city}", "licensed {service} {city}", "electrical repair {city}"],
    "general_contractor":  ["contractor near me", "home renovation {city}", "remodeling contractor {city}", "construction company {city}", "general contractor near me"],
    "roofing_contractor":  ["roofer near me", "roof repair {city}", "roofing company {city}", "emergency roof repair {city}", "roof replacement {city}"],
    "painter":             ["painter near me", "house painting {city}", "interior painter {city}", "exterior painting {city}", "commercial painter {city}"],
    "locksmith":           ["locksmith near me", "emergency locksmith {city}", "24 hour locksmith {city}", "car locksmith {city}", "locksmith services {city}"],
    "car_repair":          ["auto repair near me", "car mechanic {city}", "oil change {city}", "auto shop {city}", "car service near me"],
    "dentist":             ["dentist near me", "emergency dentist {city}", "dental clinic {city}", "teeth cleaning {city}", "best dentist {city}"],
    "doctor":              ["doctor near me", "primary care {city}", "family doctor {city}", "urgent care {city}", "physician near me"],
    "chiropractor":        ["chiropractor near me", "back pain relief {city}", "chiropractic clinic {city}", "best chiropractor {city}", "spine specialist {city}"],
    "beauty_salon":        ["hair salon near me", "hair cut {city}", "best hair salon {city}", "hair stylist {city}", "salon near me"],
    "nail_salon":          ["nail salon near me", "manicure {city}", "pedicure near me", "best nail salon {city}", "gel nails {city}"],
    "spa":                 ["spa near me", "massage near me", "day spa {city}", "facial {city}", "relaxation spa {city}"],
    "gym":                 ["gym near me", "fitness center {city}", "personal trainer {city}", "workout gym {city}", "best gym {city}"],
    "restaurant":          ["restaurant near me", "best restaurant {city}", "food near me", "lunch near me", "dinner {city}"],
    "cafe":                ["coffee shop near me", "cafe near me", "best coffee {city}", "espresso near me", "coffee near me"],
    "bakery":              ["bakery near me", "best bakery {city}", "custom cakes {city}", "fresh bread {city}", "pastries near me"],
    "bar":                 ["bar near me", "sports bar {city}", "best bar {city}", "happy hour {city}", "cocktail bar near me"],
    "florist":             ["florist near me", "flower delivery {city}", "wedding flowers {city}", "flower shop {city}", "custom bouquet {city}"],
    "pet_store":           ["pet store near me", "dog grooming {city}", "pet grooming near me", "pet supplies {city}", "vet near me"],
    "veterinary_care":     ["vet near me", "veterinarian {city}", "emergency vet {city}", "animal hospital {city}", "pet clinic near me"],
    "real_estate_agency":  ["real estate agent near me", "homes for sale {city}", "realtor {city}", "buy home {city}", "sell home {city}"],
    "accounting":          ["accountant near me", "CPA {city}", "tax preparation {city}", "bookkeeping {city}", "small business accountant {city}"],
    "lawyer":              ["lawyer near me", "attorney {city}", "law firm {city}", "legal services {city}", "free consultation lawyer {city}"],
    "moving_company":      ["movers near me", "moving company {city}", "local movers {city}", "cheap movers {city}", "residential movers {city}"],
    "cleaning_service":    ["cleaning service near me", "house cleaning {city}", "maid service {city}", "commercial cleaning {city}", "deep cleaning near me"],
    "landscaping":         ["landscaping near me", "lawn care {city}", "landscape company {city}", "lawn mowing {city}", "yard work {city}"],
    "pest_control":        ["pest control near me", "exterminator {city}", "bug control {city}", "termite treatment {city}", "rodent removal {city}"],
    "hvac_contractor":     ["HVAC near me", "AC repair {city}", "heating and cooling {city}", "air conditioning repair {city}", "furnace repair {city}"],
    "insurance_agency":    ["insurance agent near me", "auto insurance {city}", "home insurance {city}", "life insurance {city}", "cheap insurance {city}"],
    "photography_studio":  ["photographer near me", "wedding photographer {city}", "portrait photographer {city}", "headshots {city}", "photo studio near me"],
    "cannabis_store":      ["dispensary near me", "cannabis dispensary {city}", "marijuana delivery {city}", "weed near me", "CBD shop {city}"],
    "tattoo_parlor":       ["tattoo shop near me", "tattoo artist {city}", "best tattoo shop {city}", "custom tattoo {city}", "piercing near me"],
    "car_wash":            ["car wash near me", "auto detailing {city}", "car detailing near me", "hand car wash {city}", "full service car wash {city}"],
    "yoga_studio":         ["yoga near me", "yoga classes {city}", "hot yoga {city}", "pilates near me", "yoga studio {city}"],
    "driving_school":      ["driving school near me", "driving lessons {city}", "learn to drive {city}", "DMV test prep {city}", "driving instructor {city}"],
    "martial_arts_school": ["martial arts near me", "karate classes {city}", "MMA gym {city}", "self defense classes near me", "jiu jitsu {city}"],
    "tutoring_service":    ["tutoring near me", "math tutor {city}", "private tutor {city}", "homework help near me", "test prep {city}"],
}
DEFAULT_KEYWORDS = [
    "{business_name} near me",
    "best {business_name} {city}",
    "{business_name} services {city}",
    "{business_name} {city}",
    "top {business_name} near me",
]

YES_WORDS = {"yes", "y", "yep", "yeah", "correct", "that's me", "that's it", "looks good", "perfect", "confirmed"}
NO_WORDS  = {"no", "n", "nope", "wrong", "not me"}


# ── Database helpers ──────────────────────────────────────────────────────────
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
    rows = db_exec("SELECT * FROM fb_lead_sessions WHERE sender_id = %s LIMIT 1", (sender_id,))
    return dict(rows[0]) if rows else None


def upsert_session(sender_id, fields):
    existing = get_session(sender_id)
    if not existing:
        fields["sender_id"] = sender_id
        cols = ", ".join(fields.keys())
        vals = ", ".join(["%s"] * len(fields))
        db_exec(
            f"INSERT INTO fb_lead_sessions ({cols}, created_at, updated_at) VALUES ({vals}, NOW(), NOW())",
            list(fields.values()),
        )
    else:
        sets = ", ".join([f"{k} = %s" for k in fields.keys()])
        db_exec(
            f"UPDATE fb_lead_sessions SET {sets}, updated_at = NOW() WHERE sender_id = %s",
            list(fields.values()) + [sender_id],
        )
    return get_session(sender_id)


def ensure_tables():
    """Create tables if they don't exist yet (idempotent)."""
    db_exec("""
        CREATE TABLE IF NOT EXISTS fb_lead_sessions (
            sender_id     TEXT PRIMARY KEY,
            step          TEXT DEFAULT 'new',
            business_name TEXT, place_id TEXT, address TEXT,
            category      TEXT, city TEXT, email TEXT, phone TEXT,
            keywords      TEXT, first_name TEXT, last_name TEXT,
            is_returning  BOOLEAN DEFAULT FALSE,
            calendly_sent BOOLEAN DEFAULT FALSE,
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            updated_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    db_exec("""
        CREATE TABLE IF NOT EXISTS fb_chat_leads (
            sender_id     TEXT PRIMARY KEY,
            business_name TEXT, place_id TEXT, address TEXT,
            category      TEXT, city TEXT, email TEXT, phone TEXT,
            keywords      TEXT,
            tag           TEXT DEFAULT 'CHAT LEAD DO NOT CALL',
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            updated_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)


# ── Facebook Messenger helpers ────────────────────────────────────────────────
def fb_send_text(recipient_id, text):
    if not FB_PAGE_ACCESS_TOKEN:
        return [{"error": "FB_PAGE_ACCESS_TOKEN not set"}]
    chunks  = [text[i:i + MAX_MSG_LENGTH] for i in range(0, len(text), MAX_MSG_LENGTH)]
    results = []
    with httpx.Client(timeout=15) as c:
        for chunk in chunks:
            r = c.post(
                GRAPH_API,
                params={"access_token": FB_PAGE_ACCESS_TOKEN},
                json={
                    "recipient":      {"id": recipient_id},
                    "message":        {"text": chunk},
                    "messaging_type": "RESPONSE",
                },
            )
            results.append({"status_code": r.status_code, "body": r.json()})
    return results


def fb_send_quick_replies(recipient_id, text, replies):
    if not FB_PAGE_ACCESS_TOKEN:
        return {"error": "FB_PAGE_ACCESS_TOKEN not set"}
    qr = [
        {"content_type": "text", "title": r["title"][:20], "payload": r.get("payload", r["title"])}
        for r in replies[:13]
    ]
    with httpx.Client(timeout=15) as c:
        r = c.post(
            GRAPH_API,
            params={"access_token": FB_PAGE_ACCESS_TOKEN},
            json={
                "recipient":      {"id": recipient_id},
                "message":        {"text": text, "quick_replies": qr},
                "messaging_type": "RESPONSE",
            },
        )
        return {"status_code": r.status_code, "body": r.json()}


# ── Google Places helpers ─────────────────────────────────────────────────────
def search_business(query):
    if not GOOGLE_PLACES_API_KEY:
        return None
    try:
        with httpx.Client(timeout=15) as c:
            r       = c.get(PLACES_SEARCH_URL, params={"query": query, "key": GOOGLE_PLACES_API_KEY})
            results = r.json().get("results", [])
            if not results:
                return None
            top = results[0]
            return {
                "place_id":        top.get("place_id"),
                "name":            top.get("name"),
                "address":         top.get("formatted_address"),
                "types":           top.get("types", []),
                "business_status": top.get("business_status", ""),
            }
    except Exception:
        return None


def get_place_category(place_id):
    if not GOOGLE_PLACES_API_KEY or not place_id:
        return None
    try:
        with httpx.Client(timeout=15) as c:
            r      = c.get(PLACES_DETAIL_URL, params={
                "place_id": place_id,
                "fields":   "name,types,formatted_address,business_status,website",
                "key":      GOOGLE_PLACES_API_KEY,
            })
            result = r.json().get("result", {})
            types  = result.get("types", [])
            skip   = {"point_of_interest", "establishment", "locality", "political", "geocode", "premise"}
            category = next((t for t in types if t not in skip), types[0] if types else None)
            return {"category": category, "all_types": types}
    except Exception:
        return None


# ── Validation helpers ────────────────────────────────────────────────────────
def is_valid_email(email):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


def is_maps_trigger(msg):
    return msg.strip().lower() == "maps"


# ── Keyword helpers ───────────────────────────────────────────────────────────
def normalise_category(raw):
    if not raw:
        return None
    normalized = raw.lower().replace(" ", "_").replace("-", "_")
    if normalized in KEYWORD_MAP:
        return normalized
    for key in KEYWORD_MAP:
        if key in normalized or normalized in key:
            return key
    return None


def build_keywords(category, city, business_name):
    cat_key  = normalise_category(category)
    city_str = city.strip().title() if city else "your city"
    if cat_key and cat_key in KEYWORD_MAP:
        templates = KEYWORD_MAP[cat_key]
        service   = cat_key.replace("_", " ").replace(" contractor", "").replace(" service", "").strip()
    else:
        templates = DEFAULT_KEYWORDS
        service   = business_name or "service"
    return [t.format(service=service, city=city_str, business_name=business_name or service) for t in templates[:5]]


# ── Qualify step handlers ─────────────────────────────────────────────────────
def check_returning_client(sender_id):
    try:
        rows = db_exec(
            "SELECT email, first_name, last_name FROM jm_fw_v2_contacts_enriched "
            "WHERE custom_field->>'cf_fb_sender_id' = %s LIMIT 1",
            (sender_id,),
        )
        return dict(rows[0]) if rows else None
    except Exception:
        return None


def handle_new(sender_id):
    returning = check_returning_client(sender_id)
    if returning:
        name = returning.get("first_name") or "there"
        upsert_session(sender_id, {"step": "returning", "is_returning": True})
        return {
            "reply": (
                f"Welcome back, {name}! 👋 Ready to book your specialist review call?\n\n"
                "Here's your scheduling link:\n"
                f"{CALENDLY_AE_URL}"
            ),
            "step": "returning",
        }
    upsert_session(sender_id, {"step": "awaiting_business"})
    return {
        "reply": (
            "👋 Hey! Thanks for reaching out to Jumper Media!\n\n"
            "To get your free 7-day Google Map Pack trial started, I just need a couple of quick details.\n\n"
            "What's the *name of your Google Business* and what *city* is it in?\n\n"
            "Example: \"Mike's Plumbing, San Diego\""
        ),
        "step": "awaiting_business",
    }


def handle_awaiting_business(sender_id, message, session):
    search_attempts = int((session or {}).get("search_attempts", 0)) + 1
    place = search_business(message)
    if not place:
        if search_attempts >= 2:
            upsert_session(sender_id, {"step": "awaiting_email", "search_attempts": search_attempts})
            return {
                "reply": (
                    "Our team will reach out to help manually. "
                    "Drop your email here and we'll get you sorted! 📧"
                ),
                "step": "awaiting_email",
            }
        upsert_session(sender_id, {"step": "awaiting_business", "search_attempts": search_attempts})
        return {
            "reply": (
                "Hmm, I couldn't find that business on Google. 🤔\n\n"
                "Could you double-check the business name and city?\n\n"
                "Example: \"Mike's Plumbing, San Diego\""
            ),
            "step": "awaiting_business",
        }
    details  = get_place_category(place["place_id"]) or {}
    category = details.get("category") or (place["types"][0] if place["types"] else "business")
    city     = message.split(",")[-1].strip() if "," in message else ""
    upsert_session(sender_id, {
        "step":            "awaiting_confirmation",
        "business_name":   place["name"],
        "place_id":        place["place_id"],
        "address":         place["address"],
        "category":        category,
        "city":            city,
        "search_attempts": 0,
    })
    return {
        "reply": (
            f"I found this listing on Google:\n\n"
            f"📍 *{place['name']}*\n{place['address']}\n\n"
            "Is this your business? Reply *YES* or *NO*."
        ),
        "step": "awaiting_confirmation",
    }


def handle_awaiting_confirmation(sender_id, message):
    msg_lower = message.strip().lower()
    if msg_lower in YES_WORDS:
        upsert_session(sender_id, {"step": "awaiting_email"})
        return {
            "reply": "Perfect! 🎉 What's the best *email address* to send your trial details to?",
            "step": "awaiting_email",
        }
    if msg_lower in NO_WORDS:
        upsert_session(sender_id, {"step": "awaiting_business"})
        return {
            "reply": (
                "No problem! Let's try again.\n\n"
                "What's the *exact name* of your Google Business and the *city*?\n\n"
                "Example: \"The Drip Garden Co., Los Angeles\""
            ),
            "step": "awaiting_business",
        }
    return {
        "reply": "Please reply *YES* if that's your business or *NO* to search again.",
        "step": "awaiting_confirmation",
    }


def handle_awaiting_email(sender_id, message):
    email = message.strip()
    if not is_valid_email(email):
        return {
            "reply": (
                "That doesn't look like a valid email. 🤔\n\n"
                "Could you double-check and send it again?\n\nExample: yourname@gmail.com"
            ),
            "step": "awaiting_email",
        }
    upsert_session(sender_id, {"step": "awaiting_phone", "email": email})
    return {
        "reply": (
            f"Got it — {email} ✅\n\n"
            "Last thing — what's your *mobile phone number*? "
            "Your specialist will use this to confirm your review call.\n\n"
            "Example: (619) 555-1234"
        ),
        "step": "awaiting_phone",
    }


def handle_awaiting_phone(sender_id, message):
    digits = re.sub(r"\D", "", message)
    if len(digits) < 10:
        return {
            "reply": (
                "That doesn't look like a valid phone number. 📱\n\n"
                "Please enter your 10-digit mobile number.\n\nExample: (619) 555-1234"
            ),
            "step": "awaiting_phone",
        }
    session  = upsert_session(sender_id, {"step": "ready_for_keywords", "phone": digits})
    business = (session or {}).get("business_name", "your business")
    return {
        "reply": (
            f"You're almost in! 🚀\n\n"
            f"Now let's pick the *3–5 keywords* we'll target during your trial for *{business}*.\n\n"
            "I'll suggest the best ones based on your business — stand by..."
        ),
        "step": "ready_for_keywords",
    }


# ── Action: qualify ───────────────────────────────────────────────────────────
def do_qualify(sender_id, message):
    if not sender_id:
        return {"error": "sender_id is required"}
    if not message:
        return {"error": "message is required"}

    ensure_tables()
    session = get_session(sender_id)
    step    = (session or {}).get("step", "new")

    if is_maps_trigger(message) or step in ("new", "start") or not session:
        result = handle_new(sender_id)
    elif step == "awaiting_business":
        result = handle_awaiting_business(sender_id, message, session)
    elif step == "awaiting_confirmation":
        result = handle_awaiting_confirmation(sender_id, message)
    elif step == "awaiting_email":
        result = handle_awaiting_email(sender_id, message)
    elif step == "awaiting_phone":
        result = handle_awaiting_phone(sender_id, message)
    elif step in ("ready_for_keywords", "awaiting_keyword_confirm", "awaiting_ae_booking", "completed", "returning"):
        result = {"reply": None, "step": step}
    else:
        upsert_session(sender_id, {"step": "awaiting_business"})
        result = {
            "reply": "Something went wrong. Let's try again — what's your Google Business name and city?",
            "step":  "awaiting_business",
        }

    result["session"] = get_session(sender_id)
    return result


# ── Action: suggest_keywords ──────────────────────────────────────────────────
def do_suggest_keywords(sender_id, user_message=""):
    if not sender_id:
        return {"error": "sender_id is required"}

    ensure_tables()
    session = get_session(sender_id)
    if not session:
        return {"error": "No session found. Run qualify (MAPS) first."}

    step = session.get("step", "")

    if step == "ready_for_keywords":
        keywords = build_keywords(session.get("category", ""), session.get("city", ""), session.get("business_name", ""))
        upsert_session(sender_id, {"step": "awaiting_keyword_confirm", "keywords": json.dumps(keywords)})
        kw_list = "\n".join([f"  {i+1}. {kw}" for i, kw in enumerate(keywords)])
        return {
            "reply": (
                f"Based on your business category, here are the top keywords we recommend:\n\n"
                f"{kw_list}\n\n"
                "Do these look right? Reply *YES* to confirm or tell me any changes "
                "(e.g. \"replace #3 with roofing company San Diego\")."
            ),
            "step":     "awaiting_keyword_confirm",
            "keywords": keywords,
            "session":  get_session(sender_id),
        }

    if step == "awaiting_keyword_confirm":
        msg_lower        = (user_message or "").strip().lower()
        current_keywords = session.get("keywords") or []
        if isinstance(current_keywords, str):
            try:
                current_keywords = json.loads(current_keywords)
            except Exception:
                current_keywords = []

        if msg_lower in YES_WORDS:
            upsert_session(sender_id, {"step": "awaiting_ae_booking"})
            return {
                "reply": (
                    "Keywords confirmed! ✅\n\n"
                    "Your free trial is being set up. 🚀\n\n"
                    "Last step — let's schedule your *specialist review call* for next week. "
                    "That's when we'll walk you through your ranking results on Zoom.\n\n"
                    "Grabbing a booking link for you..."
                ),
                "step":     "awaiting_ae_booking",
                "keywords": current_keywords,
                "session":  get_session(sender_id),
            }

        match = re.search(r"replace\s+#?(\d)\s+with\s+(.+)", msg_lower)
        if match:
            idx    = int(match.group(1)) - 1
            new_kw = match.group(2).strip()
            if 0 <= idx < len(current_keywords):
                current_keywords[idx] = new_kw
                upsert_session(sender_id, {"keywords": json.dumps(current_keywords)})

        kw_list = "\n".join([f"  {i+1}. {kw}" for i, kw in enumerate(current_keywords)])
        return {
            "reply": (
                f"Updated! Here's the revised keyword list:\n\n{kw_list}\n\n"
                "Reply *YES* to confirm or continue making changes."
            ),
            "step":     "awaiting_keyword_confirm",
            "keywords": current_keywords,
            "session":  get_session(sender_id),
        }

    return {"reply": None, "step": step, "session": session}


# ── Action: book_ae_call ──────────────────────────────────────────────────────
def do_book_ae_call(sender_id):
    if not sender_id:
        return {"error": "sender_id is required"}

    ensure_tables()
    session = get_session(sender_id)
    if not session:
        return {"error": "No session found. Run qualify (MAPS) first."}

    # Write to CRM staging table
    try:
        db_exec(
            """
            INSERT INTO fb_chat_leads
                (sender_id, business_name, place_id, address, category, city,
                 email, phone, keywords, tag, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (sender_id) DO UPDATE SET
                email      = EXCLUDED.email,
                phone      = EXCLUDED.phone,
                keywords   = EXCLUDED.keywords,
                updated_at = NOW()
            """,
            (
                session.get("sender_id"), session.get("business_name"), session.get("place_id"),
                session.get("address"),   session.get("category"),      session.get("city"),
                session.get("email"),     session.get("phone"),          session.get("keywords"),
                "CHAT LEAD DO NOT CALL",
            ),
        )
    except Exception:
        pass  # Best-effort CRM write; don't block the booking message

    upsert_session(sender_id, {"step": "completed", "calendly_sent": True})

    business_name = session.get("business_name", "your business")
    first_name    = session.get("first_name") or ""

    target_date = datetime.utcnow() + timedelta(days=7)
    while target_date.weekday() >= 5:
        target_date += timedelta(days=1)
    target_str = target_date.strftime("%A, %B %-d")

    greeting = f"Amazing{', ' + first_name if first_name else ''}!"

    reply = (
        f"{greeting} 🎉 Your free 7-day Google Map Pack trial for *{business_name}* is all set!\n\n"
        f"Last step — book your *specialist review call*. That's a Zoom call where we'll walk you through "
        f"your live ranking results and before-and-after data.\n\n"
        f"📅 We recommend *{target_str}* — 7 days in, so we can show you real results.\n\n"
        f"👉 Book here:\n{CALENDLY_AE_URL}\n\n"
        f"*Before your call:*\n"
        f"• Be in front of a computer (dashboard is hard to view on mobile)\n"
        f"• Watch the 2-min prep video you'll receive by email\n\n"
        f"We're excited to show you results! 🚀"
    )

    return {
        "reply":        reply,
        "step":         "completed",
        "calendly_url": CALENDLY_AE_URL,
        "session":      get_session(sender_id),
    }


# ── Action: send_message ──────────────────────────────────────────────────────
def do_send_message(inp):
    recipient_id  = inp.get("recipient_id", "").strip()
    text          = inp.get("text", "").strip()
    quick_replies = inp.get("quick_replies")

    if not recipient_id:
        return {"error": "recipient_id is required"}
    if not text:
        return {"error": "text is required"}
    if not FB_PAGE_ACCESS_TOKEN:
        return {"error": "FB_PAGE_ACCESS_TOKEN env var not set"}

    if quick_replies:
        result = fb_send_quick_replies(recipient_id, text, quick_replies)
    else:
        result = fb_send_text(recipient_id, text)

    return {"status": "ok", "result": result}


# ── Action: handle_message (master dispatcher) ────────────────────────────────
def do_handle_message(sender_id, message):
    """
    Master entry-point for every inbound Messenger message.
    Determines the correct sub-flow, sends the reply via Messenger,
    and returns a summary.
    """
    if not sender_id:
        return {"error": "sender_id is required"}
    if message is None:
        return {"error": "message is required"}

    ensure_tables()
    session = get_session(sender_id)
    step    = (session or {}).get("step", "new")
    reply   = None
    next_step = step

    # ── MAPS trigger always restarts
    if is_maps_trigger(message):
        result    = do_qualify(sender_id, message)
        reply     = result.get("reply")
        next_step = result.get("step", step)

    # ── Qualification steps
    elif step in ("new", "start", "awaiting_business", "awaiting_confirmation",
                  "awaiting_email", "awaiting_phone") or not session:
        result    = do_qualify(sender_id, message)
        reply     = result.get("reply")
        next_step = result.get("step", step)

        # If just transitioned to ready_for_keywords, trigger keyword suggestion immediately
        if next_step == "ready_for_keywords":
            if reply:
                fb_send_text(sender_id, reply)
            kw_result = do_suggest_keywords(sender_id, "")
            reply     = kw_result.get("reply")
            next_step = kw_result.get("step", next_step)

    # ── Keyword suggestion / confirmation
    elif step in ("ready_for_keywords", "awaiting_keyword_confirm"):
        result    = do_suggest_keywords(sender_id, message)
        reply     = result.get("reply")
        next_step = result.get("step", step)

        # If keywords confirmed, immediately book AE call
        if next_step == "awaiting_ae_booking":
            if reply:
                fb_send_text(sender_id, reply)
            ae_result = do_book_ae_call(sender_id)
            reply     = ae_result.get("reply")
            next_step = ae_result.get("step", next_step)

    # ── AE booking
    elif step == "awaiting_ae_booking":
        ae_result = do_book_ae_call(sender_id)
        reply     = ae_result.get("reply")
        next_step = ae_result.get("step", step)

    # ── Returning client — Calendly already sent
    elif step == "returning":
        reply     = None
        next_step = "returning"

    # ── Completed
    elif step == "completed":
        reply     = None
        next_step = "completed"

    # ── Unrecognised message with no active flow
    else:
        reply     = "Want to pick up where you left off with your free trial setup? Reply MAPS to begin."
        next_step = step

    # ── Deliver reply via Messenger
    send_result = None
    if reply:
        send_result = fb_send_text(sender_id, reply)

    return {
        "step":         next_step,
        "reply_sent":   bool(reply and send_result),
        "send_result":  send_result,
        "session":      get_session(sender_id),
    }


# ── Main dispatch ─────────────────────────────────────────────────────────────
try:
    inp       = json.loads(os.environ.get("INPUT_JSON", "{}"))
    action    = inp.get("action", "").strip()
    sender_id = inp.get("sender_id", "").strip()
    message   = inp.get("message", "")

    if action == "handle_message":
        result = do_handle_message(sender_id, message)

    elif action == "send_message":
        result = do_send_message(inp)

    elif action == "qualify":
        if not sender_id:
            result = {"error": "sender_id is required"}
        elif not message:
            result = {"error": "message is required"}
        else:
            result = do_qualify(sender_id, message)

    elif action == "suggest_keywords":
        result = do_suggest_keywords(sender_id, message)

    elif action == "book_ae_call":
        result = do_book_ae_call(sender_id)

    else:
        result = {
            "error": f"Unknown action: '{action}'. "
                     "Valid actions: handle_message, send_message, qualify, suggest_keywords, book_ae_call"
        }

    print(json.dumps({"status": "ok", "result": result}, default=str))

except Exception as e:
    print(json.dumps({"error": str(e)}))