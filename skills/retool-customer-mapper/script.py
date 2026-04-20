import os
import json
import re
import html
import httpx
import psycopg2
import psycopg2.extras

# ── Database ──────────────────────────────────────────────────────────────────
DB_DSN = os.environ.get(
    "RETOOL_DB_URL",
    "postgresql://retool:npg_H0EaIfvzmg3Q@ep-small-surf-a6occgdz-pooler.us-west-2"
    ".retooldb.com/retool?sslmode=require"
)

# ── Xano ──────────────────────────────────────────────────────────────────────
XANO_URL = "https://xktx-zdsw-4yq2.n7.xano.io/api:F6QZTCZX/clientSummary"
XANO_SEC = os.environ.get("XANO_SEC", "arslan2025")

MISSING = "not present in available records"


# ── DB helpers ────────────────────────────────────────────────────────────────
def db_fetchone(sql, params=()):
    conn = psycopg2.connect(DB_DSN, connect_timeout=20)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


def db_fetchall(sql, params=()):
    conn = psycopg2.connect(DB_DSN, connect_timeout=20)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


# ── Identifier classifier ─────────────────────────────────────────────────────
def classify_identifier(identifier):
    identifier = identifier.strip()
    if "@" in identifier:
        return "email"
    digits = re.sub(r"\D", "", identifier)
    if len(digits) >= 7:
        return "phone"
    return "name"


def normalise_phone(raw):
    """Return list of phone variants to match."""
    digits = re.sub(r"\D", "", raw)
    variants = [digits]
    if len(digits) == 10:
        variants += [f"1{digits}", f"+1{digits}"]
    elif len(digits) == 11 and digits.startswith("1"):
        core = digits[1:]
        variants += [core, f"+{digits}"]
    elif len(digits) == 12 and digits.startswith("+1"):
        core = digits[2:]
        variants += [core, f"1{core}"]
    return list(dict.fromkeys(variants))


# ── Step 1 — Contact lookup ───────────────────────────────────────────────────
def lookup_contact(identifier):
    kind = classify_identifier(identifier)

    if kind == "email":
        row = db_fetchone(
            "SELECT * FROM jm_fw_v2_contacts_enriched WHERE LOWER(email) = LOWER(%s) LIMIT 1",
            (identifier,),
        )
        return dict(row) if row else None

    if kind == "phone":
        variants = normalise_phone(identifier)
        placeholders = ",".join(["%s"] * len(variants))
        sql = f"""
            SELECT * FROM jm_fw_v2_contacts_enriched
            WHERE resolved_phone_number IN ({placeholders})
               OR work_number IN ({placeholders})
            LIMIT 1
        """
        row = db_fetchone(sql, variants + variants)
        return dict(row) if row else None

    # name
    row = db_fetchone(
        "SELECT * FROM jm_fw_v2_contacts_enriched "
        "WHERE LOWER(CONCAT(first_name,' ',last_name)) LIKE LOWER(%s) LIMIT 1",
        (f"%{identifier}%",),
    )
    return dict(row) if row else None


# ── Step 2 — Deal lookup ──────────────────────────────────────────────────────
def lookup_deal(contact, identifier=None):
    deal_id    = contact.get("deal_id")
    contact_id = contact.get("contact_id")

    # 1. Direct deal_id on contact
    if deal_id:
        row = db_fetchone(
            "SELECT id, name, amount, closed_date, custom_field FROM jm_fw_all_deals WHERE id = %s LIMIT 1",
            (deal_id,),
        )
        return dict(row) if row else None

    # 2. Match by contact_id in contact_ids array
    if contact_id:
        row = db_fetchone(
            "SELECT id, name, amount, closed_date, custom_field FROM jm_fw_all_deals "
            "WHERE contact_ids::text LIKE %s ORDER BY created_at DESC LIMIT 1",
            (f"%{contact_id}%",),
        )
        if row:
            return dict(row)

    # 3. Fallback — match by email username or name as deal name
    # Handles cases where the business deal is linked to a different personal contact
    if identifier:
        # Strip domain from email to get username/business name
        search_term = identifier.split("@")[0] if "@" in identifier else identifier
        # Remove common separators for fuzzy match
        search_term = search_term.replace(".", " ").replace("_", " ").replace("-", " ").strip()
        if len(search_term) >= 4:
            row = db_fetchone(
                "SELECT id, name, amount, closed_date, custom_field FROM jm_fw_all_deals "
                "WHERE LOWER(name) LIKE LOWER(%s) ORDER BY created_at DESC LIMIT 1",
                (f"%{search_term}%",),
            )
            if row:
                return dict(row)

    return None


# ── Step 3 — Resolve GMB ID ───────────────────────────────────────────────────
def extract_gmbs_id_from_url(url):
    if not url:
        return None
    m = re.search(r"[?&]gmbs_id=([^&]+)", url)
    return m.group(1).strip() if m else None


def strip_legal_suffix(name):
    """Remove common suffixes before fuzzy name lookup."""
    name = re.sub(r",?\s*(LLP|LLC|Inc\.?|Corp\.?|Ltd\.?)$", "", name, flags=re.IGNORECASE)
    return name.strip().split()[0] if name.strip() else name.strip()


def resolve_gmbs_id(contact, deal, gmbs_override=None):
    if gmbs_override:
        return str(gmbs_override).strip(), "override"

    # 1. contact custom_field
    cf_contact = contact.get("custom_field") or {}
    if isinstance(cf_contact, str):
        try:
            cf_contact = json.loads(cf_contact)
        except Exception:
            cf_contact = {}
    gmb = cf_contact.get("cf_gmbplaceid")
    if gmb:
        return str(gmb).strip(), "contact_custom_field"

    # 2. deal custom_field purchase link
    if deal:
        cf_deal = deal.get("custom_field") or {}
        if isinstance(cf_deal, str):
            try:
                cf_deal = json.loads(cf_deal)
            except Exception:
                cf_deal = {}
        purchase_link = cf_deal.get("cf_purchase_link", "")
        gmb = extract_gmbs_id_from_url(purchase_link)
        if gmb:
            return gmb, "deal_purchase_link"

    # 3. backfill table — try deal name first, then contact ig handle
    company = None
    if deal:
        cf_deal = deal.get("custom_field") or {}
        if isinstance(cf_deal, str):
            try:
                cf_deal = json.loads(cf_deal)
            except Exception:
                cf_deal = {}
        company = deal.get("name") or cf_deal.get("cf_ig_handle")
    if not company:
        cf_contact = contact.get("custom_field") or {}
        if isinstance(cf_contact, str):
            try:
                cf_contact = json.loads(cf_contact)
            except Exception:
                cf_contact = {}
        company = cf_contact.get("cf_ig_handle")

    if company:
        first_part = strip_legal_suffix(company)
        if first_part:
            row = db_fetchone(
                "SELECT id FROM backfill_gmbs_names_and_other "
                "WHERE lower(business_name) ILIKE %s LIMIT 1",
                (f"%{first_part.lower()}%",),
            )
            if row:
                return str(row["id"]), "backfill_table"

    return None, None


# ── Step 4 — Xano keywords ────────────────────────────────────────────────────
def fetch_keywords(gmbs_id):
    if not gmbs_id:
        return []
    try:
        with httpx.Client(timeout=20) as c:
            r = c.get(XANO_URL, params={"sec": XANO_SEC, "gmbs_id": gmbs_id})
            if r.status_code >= 400:
                return None
            data = r.json()
            kws = data.get("monitoredKWs1", [])
            result = []
            for kw in kws:
                perf_raw = kw.get("solvDiff", 0)
                try:
                    perf_raw = max(0, min(100, int(float(perf_raw))))
                except (TypeError, ValueError):
                    perf_raw = 0
                result.append({
                    "keyword":     html.escape(str(kw.get("keyword", "") or "")),
                    "performance": f"{perf_raw}%",
                    "raw":         perf_raw,
                })
            return result
    except Exception:
        return None


# ── Markdown formatter ────────────────────────────────────────────────────────
def build_markdown(data):
    d = data
    lines = [
        f"## 👤 Customer Profile: {d.get('name', 'N/A')}",
        "",
        f"**Email:** {d.get('email', 'N/A')}  ",
        f"**Phone:** {d.get('phone', 'N/A')}  ",
        f"**Company:** {d.get('company', 'N/A')}  ",
        "",
        "### 🤝 Team Assignment",
        f"- **CSR:** {d.get('csr_name', 'N/A')} ({d.get('csr_email', 'N/A')})  ",
        f"- **SDR:** {d.get('sdr_name', 'N/A')}  ",
        "",
        "### 📦 Product & Billing",
        f"- **Product:** {d.get('product_name', 'N/A')}  ",
        f"- **Billing Status:** {d.get('billing_status', 'N/A')}  ",
        f"- **Last Deal Stage:** {d.get('last_deal_stage', 'N/A')}  ",
        f"- **Satisfaction Score:** {d.get('sat_score', 'N/A')}  ",
        "",
        "### 📅 Meetings",
        f"- **Last Meeting:** {d.get('last_meeting_date', 'N/A')}  ",
        f"- **Next Meeting:** {d.get('next_meeting_date', 'N/A')} ({d.get('next_meeting_status', 'N/A')})  ",
    ]

    deal = d.get("deal") or {}
    if deal:
        lines += [
            "",
            "### 💼 Deal",
            f"- **Deal ID:** {deal.get('deal_id', 'N/A')}  ",
            f"- **Name:** {deal.get('deal_name', 'N/A')}  ",
            f"- **Stage:** {deal.get('deal_stage', 'N/A')}  ",
            f"- **Value:** {deal.get('deal_value', 'N/A')}  ",
            f"- **Close Date:** {deal.get('close_date', 'N/A')}  ",
        ]

    lines += ["", f"### 🗺️ GMB ID: {d.get('gmbs_id', 'N/A')} _(source: {d.get('gmbs_id_source', 'N/A')})_"]

    keywords = d.get("keywords")
    if keywords is None:
        lines += ["", "### 🔍 Keywords", "_API unavailable_"]
    elif not keywords:
        lines += ["", "### 🔍 Keywords", "_No GMB ID — keywords unavailable_"]
    else:
        lines += ["", "### 🔍 Keyword Performance"]
        for kw in keywords:
            bar = "█" * (kw["raw"] // 10) + "░" * (10 - kw["raw"] // 10)
            lines.append(f"- **{kw['keyword']}**: {bar} {kw['performance']}")

    missing = d.get("missing", [])
    if missing:
        lines += ["", "### ⚠️ Missing Data", "- " + "\n- ".join(missing)]

    return "\n".join(lines)


# ── Main resolver ─────────────────────────────────────────────────────────────
def run(client_identifier, gmbs_override=None):
    missing = []

    contact = lookup_contact(client_identifier)
    if not contact:
        return {"error": f"No contact found for '{client_identifier}'"}

    cf = contact.get("custom_field") or {}
    if isinstance(cf, str):
        try:
            cf = json.loads(cf)
        except Exception:
            cf = {}

    deal = lookup_deal(contact, client_identifier)
    deal_cf = {}
    if deal:
        deal_cf = deal.get("custom_field") or {}
        if isinstance(deal_cf, str):
            try:
                deal_cf = json.loads(deal_cf)
            except Exception:
                deal_cf = {}

    company = None
    if deal:
        company = deal.get("name") or deal_cf.get("cf_ig_handle")
    if not company:
        company = cf.get("cf_ig_handle")

    gmbs_id, gmbs_source = resolve_gmbs_id(contact, deal, gmbs_override)
    if not gmbs_id:
        missing.append("gmbs_id — no GMB ID found in contact, deal, or backfill table")

    keywords = fetch_keywords(gmbs_id)
    if keywords is None:
        missing.append("keywords (Xano API error)")
        keywords = []

    deal_data = None
    if deal:
        amount = deal.get("amount")
        try:
            deal_value_str = f"${float(amount):,.2f}" if amount is not None else "N/A"
        except (TypeError, ValueError):
            deal_value_str = str(amount) if amount is not None else "N/A"
        deal_data = {
            "deal_id":    deal.get("id"),
            "deal_name":  deal.get("name") or "",
            "deal_stage": contact.get("deal_stage_name") or "",
            "deal_value": deal_value_str,
            "close_date": str(deal.get("closed_date", "")) if deal.get("closed_date") else "N/A",
        }
    else:
        missing.append("deal record not found")

    full_name = " ".join(filter(None, [contact.get("first_name"), contact.get("last_name")])) or client_identifier

    data = {
        "name":               full_name,
        "first_name":         contact.get("first_name") or "",
        "last_name":          contact.get("last_name") or "",
        "email":              contact.get("email") or "",
        "phone":              contact.get("resolved_phone_number") or contact.get("work_number") or "",
        "company":            company or "",
        "csr_name":           contact.get("csr_name") or cf.get("cf_csr_owner") or deal_cf.get("cf_csr_owner") or MISSING,
        "csr_email":          contact.get("csr_email") or MISSING,
        "sdr_name":           contact.get("sdr_name") or cf.get("cf_sdr_rep") or deal_cf.get("cf_sdr_rep") or MISSING,
        "product_name":       cf.get("cf_product_name") or MISSING,
        "billing_status":     cf.get("cf_billing_status") or MISSING,
        "last_deal_stage":    cf.get("cf_last_deal_stage_name") or contact.get("deal_stage_name") or MISSING,
        "sat_score":          contact.get("sat_score") or cf.get("cf_customer_sat_score") or None,
        "last_meeting_date":  str(contact.get("last_meeting_date", "")) if contact.get("last_meeting_date") else "",
        "next_meeting_date":  str(contact.get("next_meeting_date", "")) if contact.get("next_meeting_date") else "",
        "next_meeting_status": contact.get("next_meeting_status") or "",
        "deal":               deal_data,
        "gmbs_id":            gmbs_id or "",
        "gmbs_id_source":     gmbs_source or "",
        "keywords":           keywords,
        "missing":            missing,
    }

    markdown = build_markdown(data)
    return {"status": "ok", "result": markdown, "data": data}


# ── Entry point ───────────────────────────────────────────────────────────────
try:
    inp               = json.loads(os.environ.get("INPUT_JSON", "{}"))
    client_identifier = inp.get("client_identifier", "").strip()
    if not client_identifier:
        print(json.dumps({"error": "Provide client_identifier (email, phone, or full name)"}))
    else:
        gmbs_override = inp.get("gmbs_id", "").strip() or None
        result        = run(client_identifier, gmbs_override)
        print(json.dumps(result, default=str))
except Exception as e:
    print(json.dumps({"error": str(e)}))
