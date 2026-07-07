"""
scoring_rules.py
Vapi GTM Reconciliation Engine

Two separate scoring systems. They are never blended.

  Lead Score       — measures lead value (fit, intent, engagement, hiring signal)
  Data Quality     — measures field completeness only

Revenue leakage risk is computed in reconcile.py using Lead Score +
structural facts (sync status, owner, lifecycle mismatch). It does not
live here.
"""

from datetime import date, datetime

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ICP_INDUSTRIES = {
    "healthcare",
    "insurance",
    "logistics",
    "home services",
    "field services",
    "marketplace",
    "tax software",
    "customer support saas",
    "developer tools",
}

# Tech stack keywords that signal relevant tooling for Vapi's use case
RELEVANT_TECH_KEYWORDS = [
    "zendesk", "intercom", "twilio", "five9", "genesys",
    "aircall", "ringcentral", "salesforce", "hubspot", "servicetitan",
    "ivr", "avaya", "cisco", "freshdesk",
]


# ---------------------------------------------------------------------------
# A. LEAD SCORE  (max 100)
# ---------------------------------------------------------------------------

def score_fit(row: dict) -> int:
    """
    Fit Score — max 35

    Uses Clay enrichment fields (industry, employee_count,
    voice_ai_use_case, voice_ai_fit, tech_stack).
    """
    points = 0

    # ICP industry — 10 pts
    industry = _val(row.get("industry")).lower()
    if industry in ICP_INDUSTRIES:
        points += 10

    # Employee count 100–5000 — 10 pts
    try:
        emp = int(row.get("employee_count", 0))
        if 100 <= emp <= 5000:
            points += 10
    except (ValueError, TypeError):
        pass

    # Clear voice AI use case — 10 pts
    # High fit = 10, Medium = 5, Low or missing = 0
    fit = _val(row.get("voice_ai_fit")).lower()
    if fit == "high":
        points += 10
    elif fit == "medium":
        points += 5

    # Relevant tech stack — 5 pts
    stack = _val(row.get("tech_stack")).lower()
    if any(kw in stack for kw in RELEVANT_TECH_KEYWORDS):
        points += 5

    return min(points, 35)


def score_intent(row: dict) -> int:
    """
    Intent Score — max 30

    Includes Vapi-specific PLG signals: docs visits, API key creation,
    test call count. These matter because Vapi is developer/API-first.

    NOTE: "Recent activity within 7 days" is relative to today.
    Mock data uses 2024 dates, so this signal will be 0 in the demo.
    In a live system it picks up real-time engagement.
    """
    points = 0

    # Pricing or demo page activity — 10 pts
    pricing = _safe_int(row.get("pricing_page_visits"))
    demo = _safe_int(row.get("demo_page_visits"))
    if pricing > 0 or demo > 0:
        points += 10

    # Docs or API docs activity — 8 pts
    docs = _safe_int(row.get("docs_page_visits"))
    api_docs = _safe_int(row.get("api_docs_visits"))
    if docs > 0 or api_docs > 0:
        points += 8

    # API key created or test calls — 8 pts
    api_key = _val(row.get("api_key_created")).lower()
    test_calls = _safe_int(row.get("test_call_count"))
    if api_key == "yes" or test_calls > 0:
        points += 8

    # Recent activity within 7 days — 4 pts
    if _within_days(row.get("last_activity_date"), 7):
        points += 4

    return min(points, 30)


def score_engagement(row: dict) -> int:
    """
    Engagement Score — max 20
    """
    points = 0

    # Demo form or contact sales submitted — 8 pts
    if _has_value(row.get("form_submit_date")):
        points += 8

    # Campaign reply — 6 pts
    if _val(row.get("campaign_reply")).lower() == "yes":
        points += 6

    # Booked demo — 6 pts
    if _val(row.get("booked_demo")).lower() == "yes":
        points += 6

    return min(points, 20)


def score_hiring_signal(row: dict) -> int:
    """
    Hiring Signal Score — max 15

    Uses Clay fields: active_job_signal and job_posted_days_ago.
    Blank active_job_signal = no signal = 0 pts.
    """
    signal = _val(row.get("active_job_signal"))
    if not signal:
        return 0

    try:
        days = int(row.get("job_posted_days_ago", 999))
    except (ValueError, TypeError):
        days = 999

    if days <= 14:
        return 15
    elif days <= 30:
        return 10
    else:
        return 5


def compute_lead_score(row: dict) -> dict:
    """
    Returns all four component scores and the total Lead Score.
    Call this with a merged row (HubSpot + Clay fields combined).
    """
    fit = score_fit(row)
    intent = score_intent(row)
    engagement = score_engagement(row)
    hiring = score_hiring_signal(row)
    return {
        "fit_score": fit,
        "intent_score": intent,
        "engagement_score": engagement,
        "hiring_signal_score": hiring,
        "lead_score": fit + intent + engagement + hiring,
    }


# ---------------------------------------------------------------------------
# B. DATA QUALITY SCORE  (max 100)
# ---------------------------------------------------------------------------

def compute_data_quality_score(row: dict) -> dict:
    """
    Data Quality Score measures field completeness only.

    Does NOT include: Salesforce owner, sync status, or cross-system
    existence. Those are structural facts that belong in revenue leakage
    risk, not completeness.

    Clay enrichment confidence >= 0.85 counts as a completeness signal
    because low-confidence enrichment means the firmographic inputs
    feeding the Lead Score may be unreliable.
    """
    points = 0
    missing = []

    # Valid email — 15 pts
    if _has_value(row.get("email")):
        points += 15
    else:
        missing.append("email")

    # Domain — 10 pts
    if _has_value(row.get("domain")):
        points += 10
    else:
        missing.append("domain")

    # Company name — 10 pts
    if _has_value(row.get("company")):
        points += 10
    else:
        missing.append("company")

    # Job title — 10 pts
    if _has_value(row.get("job_title")):
        points += 10
    else:
        missing.append("job_title")

    # Lifecycle stage — 10 pts
    if _has_value(row.get("lifecycle_stage")):
        points += 10
    else:
        missing.append("lifecycle_stage")

    # UTM source — 10 pts
    if _has_value(row.get("utm_source")):
        points += 10
    else:
        missing.append("utm_source")

    # UTM campaign — 10 pts
    if _has_value(row.get("utm_campaign")):
        points += 10
    else:
        missing.append("utm_campaign")

    # Lead source — 5 pts
    if _has_value(row.get("lead_source")):
        points += 5
    else:
        missing.append("lead_source")

    # Clay enrichment confidence >= 0.85 — 15 pts
    try:
        confidence = float(row.get("clay_enrichment_confidence", 0))
        if confidence >= 0.85:
            points += 15
        else:
            missing.append("clay_enrichment_confidence_low")
    except (ValueError, TypeError):
        missing.append("clay_enrichment_confidence_missing")

    # Recent activity date — 5 pts
    if _has_value(row.get("last_activity_date")):
        points += 5
    else:
        missing.append("last_activity_date")

    return {
        "data_quality_score": min(points, 100),
        "missing_fields": "; ".join(missing) if missing else "none",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_email(email: str) -> str:
    """Lowercase and strip. Used as the canonical join key across all files."""
    return str(email).strip().lower()


def get_domain_from_email(email: str) -> str:
    """Extract domain portion of an email address."""
    try:
        return normalize_email(email).split("@")[1]
    except IndexError:
        return ""


def _val(v) -> str:
    """Return stripped string or empty string if None/nan."""
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "n/a") else s


def _has_value(v) -> bool:
    return bool(_val(v))


def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _within_days(date_str, days: int) -> bool:
    """True if date_str is within `days` days of today."""
    if not _has_value(date_str):
        return False
    try:
        d = datetime.strptime(_val(date_str), "%Y-%m-%d").date()
        return (date.today() - d).days <= days
    except ValueError:
        return False
