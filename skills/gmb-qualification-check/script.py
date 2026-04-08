import os
import json
import httpx

PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def places_api(api_key: str, place_id: str, timeout: int = 20) -> dict:
    """Fetch fresh Place Details from Google Places API."""
    params = {
        "place_id": place_id,
        "fields": "place_id,name,formatted_address,opening_hours,website,rating,user_ratings_total",
        "key": api_key,
    }
    with httpx.Client(timeout=timeout) as client:
        r = client.get(PLACES_DETAILS_URL, params=params)
        if r.status_code >= 400:
            raise Exception(f"Google Places API HTTP {r.status_code}: {r.text[:400]}")
        body = r.json()
        status = body.get("status", "")
        if status not in ("OK", "ZERO_RESULTS"):
            raise Exception(f"Google Places API error: {status} — {body.get('error_message', '')}")
        return body.get("result", {})


# ---------------------------------------------------------------------------
# Data normalisation
# ---------------------------------------------------------------------------

def normalise_place_result(raw: dict) -> dict:
    """Convert a raw Places API result into the standard gmb_data shape."""
    opening_hours = raw.get("opening_hours", {})
    has_hours = bool(opening_hours.get("periods") or opening_hours.get("weekday_text"))
    return {
        "place_id": raw.get("place_id", ""),
        "name": raw.get("name", ""),
        "formatted_address": raw.get("formatted_address", ""),
        "has_hours": has_hours,
        "website": raw.get("website", ""),
        "review_count": int(raw.get("user_ratings_total", 0)),
        "rating": float(raw.get("rating", 0.0)),
    }


# ---------------------------------------------------------------------------
# Core qualification logic
# ---------------------------------------------------------------------------

HOURS_MSG = (
    "Before we move forward, I noticed your Google listing is missing business hours. "
    "You'll need to add those to your GMB profile first — once you've done that, come back "
    "and let me know and I'll pick up right where we left off! 🙌"
)

WEBSITE_MSG = (
    "Thanks for confirming! Unfortunately, our program is currently only available to businesses "
    "with an active website linked to their Google listing. If you get a website set up, "
    "we'd love to have you back! 😊"
)

REVIEWS_MSG_TEMPLATE = (
    "Thanks! One thing — our program requires at least 10 Google reviews to get started, "
    "and your listing currently has {review_count}. A few things that can help: ask recent "
    "customers directly, add a review link to your email signature, or share it on social media. "
    "Once you hit 10, come back and we'll get you set up! ⭐"
)

RATING_MSG_TEMPLATE = (
    "Thanks for confirming! At the moment, our program requires a Google rating above 3.0, "
    "and yours is currently {rating}. The best way to bring it up is by responding to existing "
    "reviews and encouraging happy customers to share their experience. "
    "Once your rating improves, we'd love to work with you! 🙏"
)


def run_qualification_checks(gmb_data: dict) -> dict:
    """
    Run all four GMB qualification checks in strict order.
    Returns a result dict describing pass/fail state.
    """
    # CHECK 1 — Business Hours
    if not gmb_data.get("has_hours"):
        return {
            "qualified": False,
            "action_required": "send_message",
            "failed_check": "has_hours",
            "end_conversation": False,
            "message": HOURS_MSG,
        }

    # CHECK 2 — Website
    website = gmb_data.get("website", "")
    if not website or not website.strip():
        return {
            "qualified": False,
            "action_required": "send_message",
            "failed_check": "website",
            "end_conversation": True,
            "message": WEBSITE_MSG,
        }

    # CHECK 3 — Review Count
    review_count = int(gmb_data.get("review_count", 0))
    if review_count < 10:
        return {
            "qualified": False,
            "action_required": "send_message",
            "failed_check": "review_count",
            "end_conversation": True,
            "message": REVIEWS_MSG_TEMPLATE.format(review_count=review_count),
        }

    # CHECK 4 — Rating
    rating = float(gmb_data.get("rating", 0.0))
    if rating <= 3.0:
        return {
            "qualified": False,
            "action_required": "send_message",
            "failed_check": "rating",
            "end_conversation": True,
            "message": RATING_MSG_TEMPLATE.format(rating=rating),
        }

    # All checks passed
    return {
        "qualified": True,
        "action_required": "proceed",
        "failed_check": None,
        "end_conversation": False,
        "message": None,
    }


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def do_check(inp: dict) -> dict:
    """Run qualification checks on a supplied gmb_data object."""
    gmb_data = inp.get("gmb_data")
    if not gmb_data or not isinstance(gmb_data, dict):
        return {"error": "Provide gmb_data object from the gmb-lookup skill (must include has_hours, website, review_count, rating)."}

    required_fields = ["has_hours", "website", "review_count", "rating"]
    missing = [f for f in required_fields if f not in gmb_data]
    if missing:
        return {"error": f"gmb_data is missing required fields: {', '.join(missing)}. Re-run gmb-lookup first."}

    result = run_qualification_checks(gmb_data)
    result["gmb_data"] = gmb_data
    return result


def do_recheck(api_key: str, inp: dict) -> dict:
    """Re-fetch fresh GMB data and re-run all four qualification checks."""
    place_id = inp.get("place_id", "").strip()
    if not place_id:
        return {"error": "Provide place_id (Google Place ID, e.g. 'ChIJ...') for recheck."}

    try:
        raw = places_api(api_key, place_id)
    except Exception as e:
        return {"error": f"Failed to fetch fresh GMB data: {str(e)}"}

    if not raw:
        return {"error": f"No Place data returned for place_id '{place_id}'. Verify the ID is correct."}

    gmb_data = normalise_place_result(raw)
    result = run_qualification_checks(gmb_data)
    result["fresh_gmb_data"] = gmb_data
    result["recheck"] = True
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

try:
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    inp = json.loads(os.environ.get("INPUT_JSON", "{}"))
    action = inp.get("action", "").strip()

    if action == "check":
        result = do_check(inp)
    elif action == "recheck":
        if not api_key:
            result = {"error": "GOOGLE_PLACES_API_KEY environment variable is not set. Required for recheck action."}
        else:
            result = do_recheck(api_key, inp)
    else:
        result = {
            "error": (
                f"Unknown action: '{action}'. "
                "Available actions: 'check' (use existing gmb_data), 'recheck' (fetch fresh data by place_id)."
            )
        }

    print(json.dumps(result))

except Exception as e:
    print(json.dumps({"error": str(e)}))