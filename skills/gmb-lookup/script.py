import os
import json
import httpx

BASE = "https://maps.googleapis.com/maps/api/place"


def api_get(endpoint, params, timeout=20):
    with httpx.Client(timeout=timeout) as c:
        r = c.get(f"{BASE}/{endpoint}/json", params=params)
        if r.status_code >= 400:
            raise Exception(f"HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        status = data.get("status", "")
        if status not in ("OK", "ZERO_RESULTS"):
            error_msg = data.get("error_message", status)
            raise Exception(f"Places API error [{status}]: {error_msg}")
        return data


def do_search(key, inp):
    business_name = inp.get("business_name", "").strip()
    if not business_name:
        return {"error": "Provide business_name (e.g. 'Jumper Media')"}

    address = inp.get("address", "").strip()
    query = f"{business_name} {address}".strip() if address else business_name

    params = {
        "query": query,
        "key": key,
    }
    data = api_get("textsearch", params)

    results = data.get("results", [])
    if not results:
        return {
            "found": False,
            "count": 0,
            "candidates": [],
            "message": (
                "No listings found. Ask the lead to verify the business name exactly "
                "as it appears when searching on Google Maps."
            ),
        }

    candidates = []
    for r in results:
        candidates.append({
            "place_id": r.get("place_id", ""),
            "name": r.get("name", ""),
            "formatted_address": r.get("formatted_address", ""),
            "rating": r.get("rating"),
            "user_ratings_total": r.get("user_ratings_total"),
        })

    count = len(candidates)
    if count == 1:
        guidance = (
            "One result found. Present the listing to the lead and ask for confirmation "
            "before retrieving full details."
        )
    else:
        guidance = (
            f"{count} results found. Ask the lead for their address to identify the correct listing, "
            "then re-run search with name + address combined."
        )

    return {
        "found": True,
        "count": count,
        "candidates": candidates,
        "guidance": guidance,
    }


def do_details(key, inp):
    place_id = inp.get("place_id", "").strip()
    if not place_id:
        return {"error": "Provide place_id (obtained from a prior search action)"}

    params = {
        "place_id": place_id,
        "fields": "place_id,name,formatted_address,opening_hours,website,rating,user_ratings_total",
        "key": key,
    }
    data = api_get("details", params)

    r = data.get("result", {})
    if not r:
        return {"error": f"No details returned for place_id: {place_id}"}

    opening_hours = r.get("opening_hours", {})
    weekday_text = opening_hours.get("weekday_text", [])
    has_hours = bool(weekday_text)

    rating = r.get("rating")
    review_count = r.get("user_ratings_total")
    website = r.get("website", "")

    qualifies = True
    disqualification_reasons = []
    if review_count is not None and review_count < 10:
        qualifies = False
        disqualification_reasons.append(f"review_count {review_count} is below minimum of 10")
    if rating is not None and rating <= 3.0:
        qualifies = False
        disqualification_reasons.append(f"rating {rating} is at or below minimum of 3.0")

    result = {
        "place_id": r.get("place_id", place_id),
        "name": r.get("name", ""),
        "formatted_address": r.get("formatted_address", ""),
        "has_hours": has_hours,
        "weekday_hours": weekday_text,
        "website": website if website else None,
        "rating": rating,
        "review_count": review_count,
        "qualifies": qualifies,
    }
    if disqualification_reasons:
        result["disqualification_reasons"] = disqualification_reasons

    return result


try:
    key = (
        os.environ.get("GOOGLE_PLACES_API_KEY")
        or os.environ.get("GOOGLE_MAPS_API_KEY")
        or os.environ.get("PLACES_API_KEY")
        or ""
    ).strip()
    if not key:
        raise Exception(
            "Google Places API key not found. Set GOOGLE_PLACES_API_KEY, "
            "GOOGLE_MAPS_API_KEY, or PLACES_API_KEY environment variable."
        )

    inp = json.loads(os.environ.get("INPUT_JSON", "{}"))
    action = inp.get("action", "").strip()

    if action == "search":
        result = do_search(key, inp)
    elif action == "details":
        result = do_details(key, inp)
    else:
        result = {
            "error": f"Unknown action: '{action}'. Available actions: search, details"
        }

    print(json.dumps(result))
except Exception as e:
    print(json.dumps({"error": str(e)}))