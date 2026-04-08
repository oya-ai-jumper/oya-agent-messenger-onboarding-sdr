import os
import json
import time

ONBOARDING_URL = "https://local.jumpermedia.co/onboarding/utm=oya"
CALENDLY_LINK = "https://calendly.com/jmpsales/google-ranking-increase-jumper-local"
CONFIRMATION_TEMPLATE = (
    "Awesome! Your free trial of Jumper Local has been initiated. "
    "You should see improved rankings in less than a week. "
    "The last step is to schedule with a specialist to go over your results. "
    "Choose a time that works best for you here: " + CALENDLY_LINK
)


def do_complete_onboarding(inp):
    gmb_name = inp.get("gmb_name", "").strip()
    gmb_address = inp.get("gmb_address", "").strip()
    lead_name = inp.get("lead_name", "").strip()
    lead_email = inp.get("lead_email", "").strip()
    lead_phone = inp.get("lead_phone", "").strip()

    if not gmb_name:
        return {"error": "Provide gmb_name (e.g. 'Joe\\'s Pizza')"}
    if not gmb_address:
        return {"error": "Provide gmb_address (e.g. '123 Main St, Austin, TX 78701')"}
    if not lead_name:
        return {"error": "Provide lead_name"}
    if not lead_email:
        return {"error": "Provide lead_email"}
    if not lead_phone:
        return {"error": "Provide lead_phone"}

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return {"error": "playwright is not installed. Add 'playwright>=1.40' to requirements and run 'playwright install chromium'."}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            page.goto(ONBOARDING_URL, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=20000)

            # ── Step 1: Enter GMB name and address ──────────────────────────
            name_selector = _find_field(page, [
                'input[name*="business"]', 'input[placeholder*="business"]',
                'input[placeholder*="name"]', 'input[id*="business"]',
                'input[id*="name"]', 'input[type="text"]:first-of-type',
            ])
            if not name_selector:
                return {"error": "Could not locate GMB name input on onboarding page (Step 1). The page layout may have changed."}
            page.fill(name_selector, gmb_name)

            address_selector = _find_field(page, [
                'input[name*="address"]', 'input[placeholder*="address"]',
                'input[id*="address"]', 'input[autocomplete*="address"]',
            ])
            if address_selector:
                page.fill(address_selector, gmb_address)

            # Submit / Next for Step 1
            _click_next(page)
            time.sleep(1.5)

            # ── Step 2: Select correct GMB from results list ─────────────────
            selected = _select_gmb_result(page, gmb_name, gmb_address)
            if not selected:
                browser.close()
                return {
                    "error": f"Could not find a matching GMB result for '{gmb_name}' at '{gmb_address}'. "
                             "Verify the business name and address then retry."
                }
            time.sleep(1.0)

            # Submit / Next for Step 2
            _click_next(page)
            time.sleep(1.5)

            # ── Step 3: Enter lead contact details ───────────────────────────
            _fill_contact(page, lead_name, lead_email, lead_phone)

            # Final submit
            _click_submit(page)
            time.sleep(2.0)

            browser.close()
            return {
                "status": "ok",
                "message": "Onboarding completed successfully",
                "gmb_name": gmb_name,
                "gmb_address": gmb_address,
                "lead_name": lead_name,
                "lead_email": lead_email,
            }

        except PWTimeout as e:
            browser.close()
            return {"error": f"Timeout during onboarding navigation: {str(e)[:300]}"}
        except Exception as e:
            browser.close()
            return {"error": f"Onboarding failed: {str(e)[:400]}"}


# ── Playwright helpers ────────────────────────────────────────────────────────

def _find_field(page, selectors):
    """Return the first selector that matches a visible input."""
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return sel
        except Exception:
            continue
    return None


def _click_next(page):
    """Click a Next/Continue button if present."""
    next_selectors = [
        'button[type="submit"]',
        'button:has-text("Next")',
        'button:has-text("Continue")',
        'input[type="submit"]',
        'a:has-text("Next")',
    ]
    for sel in next_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                return
        except Exception:
            continue


def _click_submit(page):
    """Click the final Submit/Finish button."""
    submit_selectors = [
        'button:has-text("Submit")',
        'button:has-text("Finish")',
        'button:has-text("Complete")',
        'button:has-text("Start")',
        'button[type="submit"]',
        'input[type="submit"]',
    ]
    for sel in submit_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                return
        except Exception:
            continue


def _select_gmb_result(page, gmb_name, gmb_address):
    """
    Try to click a result list item that matches gmb_name or gmb_address.
    Returns True if a match was clicked, False otherwise.
    """
    result_selectors = [
        'li[class*="result"]', 'div[class*="result"]',
        'li[class*="item"]', 'div[class*="item"]',
        'ul > li', 'ol > li',
        '[role="option"]', '[role="listitem"]',
    ]
    name_lower = gmb_name.lower()
    addr_lower = gmb_address.lower()

    for sel in result_selectors:
        try:
            items = page.query_selector_all(sel)
            for item in items:
                text = (item.inner_text() or "").lower()
                if name_lower in text or addr_lower in text:
                    item.click()
                    return True
        except Exception:
            continue

    # Fallback: look for any visible element containing the name text
    try:
        el = page.get_by_text(gmb_name, exact=False).first
        if el and el.is_visible():
            el.click()
            return True
    except Exception:
        pass

    return False


def _fill_contact(page, lead_name, lead_email, lead_phone):
    """Fill lead contact fields in Step 3."""
    field_map = [
        (["input[name*='name']", "input[placeholder*='name']", "input[id*='name']"], lead_name),
        (["input[name*='email']", "input[placeholder*='email']", "input[type='email']"], lead_email),
        (["input[name*='phone']", "input[placeholder*='phone']", "input[type='tel']",
          "input[id*='phone']"], lead_phone),
    ]
    for selectors, value in field_map:
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.fill(value)
                    break
            except Exception:
                continue


# ── Action: send_confirmation ─────────────────────────────────────────────────

def do_send_confirmation(inp):
    lead_name = inp.get("lead_name", "").strip()
    return {
        "status": "ok",
        "lead_name": lead_name or "Lead",
        "confirmation_message": CONFIRMATION_TEMPLATE,
        "calendly_link": CALENDLY_LINK,
    }


# ── Main dispatch ─────────────────────────────────────────────────────────────

try:
    inp = json.loads(os.environ.get("INPUT_JSON", "{}"))
    action = inp.get("action", "")

    if action == "complete_onboarding":
        result = do_complete_onboarding(inp)
    elif action == "send_confirmation":
        result = do_send_confirmation(inp)
    else:
        result = {
            "error": f"Unknown action: '{action}'. Available actions: complete_onboarding, send_confirmation"
        }

    print(json.dumps(result))

except Exception as e:
    print(json.dumps({"error": str(e)}))