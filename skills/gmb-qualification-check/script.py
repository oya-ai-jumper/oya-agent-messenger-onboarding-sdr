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
    "Looks like your Google Business Profile doesn't meet all of our requirements. "
    "Please add business hours to your profile and try again."
)

WEBSITE_MSG = (
    "Looks like your Google Business Profile doesn't meet all of our requirements. "
    "Please add a website to your profile and try again."
)

REVIEWS_MSG_TEMPLATE = (
    "Looks like your Google Business Profile doesn't meet all of our requirements. "
    "We need to see at least 10 reviews on your profile."
)

RATING_MSG_TEMPLATE = (
    "Looks like your Google Business Profile doesn't meet all of our requirements. "
    "We need to see at least a 3.0 or higher rating on your Google Business Profile."
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
            "message": REVIEWS_MSG_TEMPLATE,
        }

    # CHECK 4 — Rating
    rating = float(gmb_data.get("rating", 0.0))
    if rating <= 3.0:
        return {
            "qualified": False,
            "action_required": "send_message",
            "failed_check": "rating",
            "end_conversation": True,
            "message": RATING_MSG_TEMPLATE,
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
    # Accept place_id at top level OR nested inside gmb_data (agent sometimes nests it)
    place_id = (inp.get("place_id") or "").strip()
    if not place_id:
        gmb_data_nested = inp.get("gmb_data") or {}
        if isinstance(gmb_data_nested, dict):
            place_id = (gmb_data_nested.get("place_id") or "").strip()
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

    if action in ("check", "recheck", ""):
        # Always fetch fresh data from Google Places — never trust LLM-supplied gmb_data
        if not api_key:
            result = {"error": "GOOGLE_PLACES_API_KEY environment variable is not set."}
        else:
            result = do_recheck(api_key, inp)
    else:
        result = {
            "error": (
                f"Unknown action: '{action}'. "
                "Use action='recheck' with place_id to run qualification checks."
            )
        }

    print(json.dumps(result))

except Exception as e:
    print(json.dumps({"error": str(e)}))