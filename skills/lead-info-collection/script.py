import os
import json
import hashlib
import tempfile

# ---------------------------------------------------------------------------
# Storage helpers — persist session data in temp files keyed by session_id
# ---------------------------------------------------------------------------

def _session_path(session_id: str) -> str:
    safe = hashlib.md5(session_id.encode()).hexdigest() if session_id else "default"
    return os.path.join(tempfile.gettempdir(), f"lead_session_{safe}.json")


def load_session(session_id: str) -> dict:
    path = _session_path(session_id)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_session(session_id: str, data: dict) -> None:
    path = _session_path(session_id)
    with open(path, "w") as f:
        json.dump(data, f)


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def do_ask_name(_inp: dict) -> dict:
    return {
        "message": "Whats your full name?",
        "field": "lead_name",
        "step": "4a",
        "instruction": "Wait for the lead to reply before proceeding to store_name."
    }


def do_store_name(inp: dict) -> dict:
    lead_name = inp.get("lead_name", "").strip()
    if not lead_name:
        return {"error": "Provide lead_name — the full name exactly as the lead provided it."}
    session_id = inp.get("session_id", "default")
    data = load_session(session_id)
    data["lead_name"] = lead_name
    save_session(session_id, data)
    return {
        "stored": True,
        "field": "lead_name",
        "value": lead_name,
        "session_id": session_id,
        "next_action": "ask_email"
    }


def do_ask_email(_inp: dict) -> dict:
    return {
        "message": "Perfect. I'll create your dashboard now. What's the best email for your login?",
        "field": "lead_email",
        "step": "4b",
        "instruction": "Wait for the lead to reply before proceeding to store_email."
    }


def do_store_email(inp: dict) -> dict:
    lead_email = inp.get("lead_email", "").strip()
    if not lead_email:
        return {"error": "Provide lead_email — the email address exactly as the lead provided it."}
    session_id = inp.get("session_id", "default")
    data = load_session(session_id)
    if "lead_name" not in data:
        return {"error": "lead_name has not been stored yet. Complete ask_name → store_name first."}
    data["lead_email"] = lead_email
    save_session(session_id, data)
    return {
        "stored": True,
        "field": "lead_email",
        "value": lead_email,
        "session_id": session_id,
        "next_action": "ask_phone"
    }


def do_ask_phone(_inp: dict) -> dict:
    return {
        "message": "And what phone number can I text your login details to? (Please include your country code, e.g. +1)",
        "field": "lead_phone",
        "step": "4c",
        "instruction": "Wait for the lead to reply before proceeding to store_phone."
    }


def do_store_phone(inp: dict) -> dict:
    lead_phone = inp.get("lead_phone", "").strip()
    if not lead_phone:
        return {"error": "Provide lead_phone — the phone number exactly as the lead provided it."}
    session_id = inp.get("session_id", "default")
    data = load_session(session_id)
    if "lead_name" not in data:
        return {"error": "lead_name has not been stored yet. Complete the full sequence in order."}
    if "lead_email" not in data:
        return {"error": "lead_email has not been stored yet. Complete ask_email → store_email first."}
    data["lead_phone"] = lead_phone
    save_session(session_id, data)
    return {
        "stored": True,
        "field": "lead_phone",
        "value": lead_phone,
        "session_id": session_id,
        "next_action": "get_collected_data"
    }


def do_get_collected_data(inp: dict) -> dict:
    session_id = inp.get("session_id", "default")
    data = load_session(session_id)
    missing = [f for f in ("lead_name", "lead_email", "lead_phone") if f not in data]
    if missing:
        return {
            "error": f"Missing fields: {', '.join(missing)}. Complete the full collection sequence before calling get_collected_data.",
            "collected_so_far": data,
            "ready_for_step_5": False
        }
    return {
        "lead_name": data["lead_name"],
        "lead_email": data["lead_email"],
        "lead_phone": data["lead_phone"],
        "session_id": session_id,
        "ready_for_step_5": True
    }


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

try:
    inp = json.loads(os.environ.get("INPUT_JSON", "{}"))
    action = inp.get("action", "")

    dispatch = {
        "ask_name": do_ask_name,
        "store_name": do_store_name,
        "ask_email": do_ask_email,
        "store_email": do_store_email,
        "ask_phone": do_ask_phone,
        "store_phone": do_store_phone,
        "get_collected_data": do_get_collected_data,
    }

    if action not in dispatch:
        result = {
            "error": f"Unknown action: '{action}'.",
            "available_actions": list(dispatch.keys()),
            "correct_order": ["ask_name", "store_name", "ask_email", "store_email", "ask_phone", "store_phone", "get_collected_data"]
        }
    else:
        result = dispatch[action](inp)

    print(json.dumps(result))

except Exception as e:
    print(json.dumps({"error": str(e)}))