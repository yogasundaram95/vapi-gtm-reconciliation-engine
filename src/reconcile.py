"""
reconcile.py
Vapi GTM Reconciliation Engine

Core reconciliation engine. Compares HubSpot contacts, Salesforce leads,
and Clay enrichment. Detects sync gaps, missing owners, lifecycle
mismatches, duplicate contacts, and missing attribution. Uses Lead Score
only to prioritize which structural problems create the most revenue risk.

Run:
    python3 src/reconcile.py
"""

import os
import csv
import sys
from collections import defaultdict
from datetime import datetime

# Allow imports from the src/ directory when running from project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scoring_rules import (
    compute_lead_score,
    compute_data_quality_score,
    normalize_email,
    get_domain_from_email,
    _has_value,
    _val,
    _safe_int,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(BASE_DIR, "data", "input")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Lifecycle alignment map
# HubSpot lifecycle_stage → acceptable Salesforce salesforce_lifecycle_stage values
# A mismatch means the two systems disagree on where this lead sits in the funnel.
# ---------------------------------------------------------------------------
HS_TO_SF_LIFECYCLE = {
    "lead":                    {"lead", "new", "open"},
    "marketing qualified lead": {"mql", "marketing qualified lead"},
    "sales qualified lead":    {"sql", "working", "sales qualified lead", "qualified"},
    "opportunity":             {"opportunity", "working", "qualified"},
    "customer":                {"customer", "closed won", "converted"},
}

# ---------------------------------------------------------------------------
# Deterministic routing segment map (one segment per ICP vertical)
# ---------------------------------------------------------------------------
SEGMENT_MAP = {
    "healthcare":            "Regulated Industries Segment",
    "insurance":             "Regulated Industries Segment",
    "tax software":          "Regulated Industries Segment",
    "logistics":             "Operations Segment",
    "field services":        "Operations Segment",
    "home services":         "Operations Segment",
    "customer support saas": "Platform Segment",
    "marketplace":           "Platform Segment",
    "developer tools":       "Platform Segment",
}


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def read_csv(filename: str) -> list[dict]:
    path = os.path.join(INPUT_DIR, filename)
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(filename: str, rows: list[dict], fieldnames: list[str] = None):
    path = os.path.join(OUTPUT_DIR, filename)
    if not rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            if fieldnames:
                csv.DictWriter(f, fieldnames=fieldnames).writeheader()
        return
    keys = fieldnames or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def is_lifecycle_mismatch(hs_stage: str, sf_stage: str) -> bool:
    """
    True when HubSpot and Salesforce disagree on funnel stage.
    Comparison is case-insensitive and whitespace-trimmed.
    Returns False if either field is blank (cannot judge).
    """
    hs = _val(hs_stage).lower()
    sf = _val(sf_stage).lower()
    if not hs or not sf:
        return False
    expected = HS_TO_SF_LIFECYCLE.get(hs)
    if expected is None:
        return False
    return sf not in expected


def classify_leakage_risk(
    lead_score: int,
    in_sf: bool,
    sf_owner: str,
    lc_mismatch: bool,
    is_dup: bool,
    utm_missing: bool,
    low_confidence: bool,
) -> str:
    """
    Revenue Leakage Risk — structural GTM risk classification.

    Uses Lead Score + structural facts only.
    Never uses Data Quality Score as an input.

    Critical  → Lead Score >= 80 AND (missing from SF OR no SF owner)
    High      → Lead Score >= 80 AND (lifecycle mismatch OR duplicate email)
    Medium    → Lead Score >= 60 AND (missing UTM OR low Clay confidence)
    Low       → Lead Score < 60 with any minor issue
    Healthy   → Synced, owned, lifecycle aligned, no dup, attribution intact
    """
    owner_missing = not _has_value(sf_owner)

    if lead_score >= 80 and (not in_sf or owner_missing):
        return "Critical"
    if lead_score >= 80 and (lc_mismatch or is_dup):
        return "High"
    if lead_score >= 60 and (utm_missing or low_confidence):
        return "Medium"
    if lead_score < 60:
        return "Low"
    return "Healthy"


def compute_sync_health(
    in_sf: bool,
    sf_owner: str,
    lc_mismatch: bool,
    is_dup: bool,
    utm_missing: bool,
) -> str:
    """
    vapi_sync_health — one-line structural status for HubSpot custom property.
    Tells Marketing and RevOps what is broken at a glance.
    Priority order: sync > owner > stage > attribution > healthy.
    """
    if not in_sf:
        return "Not in Salesforce"
    if is_dup:
        return "Duplicate Contact"
    if not _has_value(sf_owner) and lc_mismatch:
        return "Synced — Missing Owner + Stage Mismatch"
    if not _has_value(sf_owner):
        return "Synced — Missing Owner"
    if lc_mismatch:
        return "Synced — Stage Mismatch"
    if utm_missing:
        return "Synced — Missing UTM"
    return "Synced — Healthy"


def get_routing(lead_score: int, in_sf: bool, sf_owner: str, lc_mismatch: bool) -> tuple[str, str]:
    """Returns (routing_recommendation, next_best_action)."""
    owner_missing = not _has_value(sf_owner)

    if lead_score >= 80:
        if not in_sf:
            rec = "RevOps Critical Fix — Add to Salesforce before Sales outreach"
            nba = "Create Salesforce lead immediately; assign to segment owner; alert RevOps"
        elif owner_missing:
            rec = "Assign Owner Immediately"
            nba = "Assign Salesforce owner by industry segment; begin outreach within 24 hours"
        elif lc_mismatch:
            rec = "Fix Lifecycle Stage Before Routing"
            nba = "Align HubSpot lifecycle and Salesforce lifecycle stage; then route to AE"
        else:
            rec = "AE Priority"
            nba = "Route to AE for immediate outreach"
    elif 60 <= lead_score <= 79:
        rec = "SDR Priority"
        nba = "Add to SDR outreach sequence within 48 hours"
    elif 40 <= lead_score <= 59:
        rec = "Nurture"
        nba = "Enroll in nurture sequence; re-score in 30 days"
    else:
        rec = "Hold / Enrich Further"
        nba = "Flag for enrichment review; do not contact until score improves"

    return rec, nba


def pick_canonical(rows: list[dict]) -> dict:
    """
    Duplicate-collapse rule for unique-lead outputs.
    Keep the record with the highest Data Quality Score.
    Tie-break: most recent last_activity_date.
    Documented in README.md.
    """
    def sort_key(r):
        dq = r.get("data_quality_score", 0)
        try:
            d = datetime.strptime(_val(r.get("last_activity_date")), "%Y-%m-%d")
        except ValueError:
            d = datetime.min
        return (dq, d)

    return max(rows, key=sort_key)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 62)
    print("  Vapi GTM Reconciliation Engine")
    print("=" * 62)

    # -----------------------------------------------------------------------
    # Step 1: Load files
    # -----------------------------------------------------------------------
    hs_rows  = read_csv("hubspot_contacts.csv")
    sf_rows  = read_csv("salesforce_leads.csv")
    clay_rows = read_csv("clay_enrichment_mock.csv")

    # -----------------------------------------------------------------------
    # Step 2: Normalize emails
    # lowercase + strip whitespace → normalized_email
    # -----------------------------------------------------------------------
    for r in hs_rows:
        r["normalized_email"] = normalize_email(r.get("email", ""))

    for r in sf_rows:
        r["normalized_email"] = normalize_email(r.get("email", ""))

    # -----------------------------------------------------------------------
    # Step 3: Detect duplicates (by normalized_email only — NOT by domain)
    # -----------------------------------------------------------------------
    hs_by_email: dict[str, list[dict]] = defaultdict(list)
    for r in hs_rows:
        if r["normalized_email"]:
            hs_by_email[r["normalized_email"]].append(r)

    duplicate_emails: set[str] = {
        email for email, rows in hs_by_email.items() if len(rows) > 1
    }

    duplicate_rows: list[dict] = []
    for email, rows in hs_by_email.items():
        if len(rows) > 1:
            ids = [r.get("hubspot_contact_id", "") for r in rows]
            companies = list({r.get("company", "") for r in rows if _has_value(r.get("company"))})
            duplicate_rows.append({
                "normalized_email":     email,
                "duplicate_count":      len(rows),
                "hubspot_contact_ids":  "; ".join(ids),
                "companies_seen":       "; ".join(companies),
                "recommended_fix":      "Merge duplicate contacts in HubSpot; keep record with highest Data Quality Score",
            })

    write_csv("duplicate_contacts.csv", duplicate_rows, fieldnames=[
        "normalized_email", "duplicate_count", "hubspot_contact_ids",
        "companies_seen", "recommended_fix",
    ])

    # -----------------------------------------------------------------------
    # Step 4: Match HubSpot to Salesforce by normalized_email
    # -----------------------------------------------------------------------
    sf_by_email: dict[str, dict] = {}
    for r in sf_rows:
        if r["normalized_email"]:
            sf_by_email[r["normalized_email"]] = r

    hs_emails = set(hs_by_email.keys())
    sf_emails = set(sf_by_email.keys())

    hs_not_in_sf = hs_emails - sf_emails          # in HubSpot, missing from Salesforce
    sf_not_in_hs = sf_emails - hs_emails          # in Salesforce, missing from HubSpot

    # -----------------------------------------------------------------------
    # Step 5: Join Clay enrichment by domain
    # Clay is account-level → domain is the correct join key here.
    # Email is used for contact deduplication; domain is used for enrichment.
    # -----------------------------------------------------------------------
    clay_by_domain: dict[str, dict] = {}
    for r in clay_rows:
        d = _val(r.get("domain")).lower()
        if d:
            clay_by_domain[d] = r

    # -----------------------------------------------------------------------
    # Build enriched rows: merge HubSpot + Salesforce + Clay for each contact
    # -----------------------------------------------------------------------
    enriched: list[dict] = []

    for r in hs_rows:
        norm  = r["normalized_email"]
        sf    = sf_by_email.get(norm, {})

        # Use domain column from HubSpot if present; fall back to extracting from email
        domain = _val(r.get("domain")).lower() or get_domain_from_email(r.get("email", ""))
        clay  = clay_by_domain.get(domain, {})

        merged = {**r}

        # Pull Clay fields into the merged row (Clay enriches HubSpot account data)
        for field in [
            "industry", "employee_count", "tech_stack", "funding_stage",
            "active_job_signal", "job_posted_days_ago", "voice_ai_use_case",
            "voice_ai_fit", "clay_enrichment_confidence", "decision_maker_title",
        ]:
            merged[field] = clay.get(field, "")

        # Salesforce context
        in_sf     = norm in sf_emails
        sf_owner  = _val(sf.get("salesforce_owner", "")) if sf else ""
        sf_lc     = _val(sf.get("salesforce_lifecycle_stage", "")) if sf else ""
        hs_lc     = _val(r.get("lifecycle_stage", ""))

        merged["in_salesforce"]               = "yes" if in_sf else "no"
        merged["salesforce_owner"]            = sf_owner
        merged["salesforce_lifecycle_stage"]  = sf_lc
        merged["salesforce_status"]           = _val(sf.get("salesforce_status", "")) if sf else ""

        # Internal flags used by scoring and risk classification
        merged["_is_duplicate"]         = norm in duplicate_emails
        merged["_lifecycle_mismatch"]   = is_lifecycle_mismatch(hs_lc, sf_lc) if in_sf else False
        merged["_in_sf"]                = in_sf

        enriched.append(merged)

    # -----------------------------------------------------------------------
    # Steps 6 & 7: Score each enriched row
    # -----------------------------------------------------------------------
    for r in enriched:
        ls = compute_lead_score(r)
        r.update(ls)
        dq = compute_data_quality_score(r)
        r.update(dq)

    # -----------------------------------------------------------------------
    # Step 8: Classify Revenue Leakage Risk
    # -----------------------------------------------------------------------
    for r in enriched:
        utm_missing = not _has_value(r.get("utm_source")) or not _has_value(r.get("utm_campaign"))

        try:
            confidence = float(r.get("clay_enrichment_confidence", 1.0))
        except (ValueError, TypeError):
            confidence = 1.0
        low_confidence = confidence < 0.85

        r["revenue_leakage_risk"] = classify_leakage_risk(
            lead_score    = r["lead_score"],
            in_sf         = r["_in_sf"],
            sf_owner      = r["salesforce_owner"],
            lc_mismatch   = r["_lifecycle_mismatch"],
            is_dup        = r["_is_duplicate"],
            utm_missing   = utm_missing,
            low_confidence= low_confidence,
        )

        rec, nba = get_routing(
            lead_score  = r["lead_score"],
            in_sf       = r["_in_sf"],
            sf_owner    = r["salesforce_owner"],
            lc_mismatch = r["_lifecycle_mismatch"],
        )
        r["routing_recommendation"] = rec
        r["next_best_action"]       = nba

        industry_key = _val(r.get("industry")).lower()
        r["suggested_routing_segment"] = SEGMENT_MAP.get(industry_key, "Unclassified")

        r["vapi_sync_health"] = compute_sync_health(
            in_sf       = r["_in_sf"],
            sf_owner    = r["salesforce_owner"],
            lc_mismatch = r["_lifecycle_mismatch"],
            is_dup      = r["_is_duplicate"],
            utm_missing = not _has_value(r.get("utm_source")) or not _has_value(r.get("utm_campaign")),
        )

    # -----------------------------------------------------------------------
    # Duplicate-collapse for unique-lead outputs
    # Per normalized_email: keep highest Data Quality Score; tie-break on
    # most recent last_activity_date. Rule documented in README.md.
    # -----------------------------------------------------------------------
    score_by_email: dict[str, list[dict]] = defaultdict(list)
    for r in enriched:
        score_by_email[r["normalized_email"]].append(r)

    unique_leads = [pick_canonical(rows) for rows in score_by_email.values()]
    unique_leads_sorted = sorted(unique_leads, key=lambda x: x["lead_score"], reverse=True)

    # -----------------------------------------------------------------------
    # Write output files
    # -----------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 1. scored_leads.csv  (supporting — unique leads, component scores)
    # ------------------------------------------------------------------
    write_csv("scored_leads.csv", unique_leads_sorted, fieldnames=[
        "email", "normalized_email", "company", "domain",
        "fit_score", "intent_score", "engagement_score", "hiring_signal_score", "lead_score",
    ])

    # ------------------------------------------------------------------
    # 2. data_quality_scores.csv  (supporting — field completeness)
    # ------------------------------------------------------------------
    write_csv("data_quality_scores.csv", unique_leads_sorted, fieldnames=[
        "email", "normalized_email", "company", "domain",
        "data_quality_score", "missing_fields",
    ])

    # ------------------------------------------------------------------
    # 3. high_intent_not_synced_to_salesforce.csv  ← hero artifact
    # Lead Score >= 80 AND missing from Salesforce
    # ------------------------------------------------------------------
    high_intent_not_synced = [
        r for r in enriched if r["lead_score"] >= 80 and not r["_in_sf"]
    ]
    high_intent_not_synced = sorted(
        high_intent_not_synced, key=lambda x: x["lead_score"], reverse=True
    )
    for r in high_intent_not_synced:
        r["intent_summary"]  = _val(r.get("voice_ai_use_case"))
        r["business_risk"]   = (
            "High-intent lead not visible to Sales — "
            "revenue leakage risk while competitor may be in contact"
        )
        r["recommended_fix"] = (
            "Create Salesforce lead immediately; assign owner "
            "by routing segment; alert Sales team"
        )
    write_csv("high_intent_not_synced_to_salesforce.csv", high_intent_not_synced, fieldnames=[
        "email", "company", "domain", "lead_score", "data_quality_score",
        "industry", "active_job_signal", "intent_summary",
        "business_risk", "recommended_fix",
    ])

    # ------------------------------------------------------------------
    # 4. missing_owner_queue.csv
    # All records (in or out of SF) with no Salesforce owner assigned
    # ------------------------------------------------------------------
    missing_owner = [
        r for r in enriched if not _has_value(r.get("salesforce_owner"))
    ]
    missing_owner = sorted(missing_owner, key=lambda x: x["lead_score"], reverse=True)
    for r in missing_owner:
        industry_key = _val(r.get("industry")).lower()
        r["action_required"]       = "Assign Salesforce owner"
        r["owner_assignment_basis"] = (
            "Not assigned in Salesforce export"
            if r["_in_sf"]
            else "Not yet synced to Salesforce — assign owner when record is created"
        )
        r["suggested_routing_segment"] = SEGMENT_MAP.get(industry_key, "Unclassified")
    write_csv("missing_owner_queue.csv", missing_owner, fieldnames=[
        "email", "company", "domain", "lead_score", "data_quality_score",
        "revenue_leakage_risk", "action_required",
        "owner_assignment_basis", "suggested_routing_segment",
    ])

    # ------------------------------------------------------------------
    # 5. lifecycle_mismatch_queue.csv
    # ------------------------------------------------------------------
    lc_mismatches = [r for r in enriched if r.get("_lifecycle_mismatch")]
    for r in lc_mismatches:
        r["hubspot_lifecycle_stage"]    = _val(r.get("lifecycle_stage"))
        r["recommended_fix"] = (
            f"Align stages — HubSpot: '{_val(r.get('lifecycle_stage'))}' "
            f"vs Salesforce: '{_val(r.get('salesforce_lifecycle_stage'))}'"
        )
    write_csv("lifecycle_mismatch_queue.csv", lc_mismatches, fieldnames=[
        "email", "company", "hubspot_lifecycle_stage", "salesforce_lifecycle_stage",
        "lead_score", "revenue_leakage_risk", "recommended_fix",
    ])

    # ------------------------------------------------------------------
    # 6. duplicate_contacts.csv  (email duplicates only — not domain)
    # lead_score_max pulled from the scored enriched rows
    # ------------------------------------------------------------------
    scored_by_email: dict[str, list[dict]] = defaultdict(list)
    for r in enriched:
        scored_by_email[r["normalized_email"]].append(r)

    duplicate_rows_out: list[dict] = []
    for email, rows in hs_by_email.items():
        if len(rows) > 1:
            ids      = [r.get("hubspot_contact_id", "") for r in rows]
            companies = list({r.get("company", "") for r in rows if _has_value(r.get("company"))})
            domains   = list({_val(r.get("domain")) for r in rows if _has_value(r.get("domain"))})
            max_ls   = max((r.get("lead_score", 0) for r in scored_by_email.get(email, [])), default=0)
            duplicate_rows_out.append({
                "normalized_email":    email,
                "duplicate_count":     len(rows),
                "hubspot_contact_ids": "; ".join(ids),
                "companies_seen":      "; ".join(companies),
                "domains_seen":        "; ".join(domains),
                "lead_score_max":      max_ls,
                "recommended_fix":     (
                    "Merge duplicate contacts in HubSpot; "
                    "keep record with highest Data Quality Score; "
                    "update Salesforce link"
                ),
            })
    write_csv("duplicate_contacts.csv", duplicate_rows_out, fieldnames=[
        "normalized_email", "duplicate_count", "hubspot_contact_ids",
        "companies_seen", "domains_seen", "lead_score_max", "recommended_fix",
    ])

    # ------------------------------------------------------------------
    # 7. missing_utm_queue.csv
    # ------------------------------------------------------------------
    missing_utm = [
        r for r in enriched
        if not _has_value(r.get("utm_source")) or not _has_value(r.get("utm_campaign"))
    ]
    for r in missing_utm:
        fields = []
        if not _has_value(r.get("utm_source")):   fields.append("utm_source")
        if not _has_value(r.get("utm_campaign")): fields.append("utm_campaign")
        r["missing_fields"]  = "; ".join(fields)
        r["recommended_fix"] = (
            "Backfill UTM source and campaign from ad platform logs, "
            "CRM import history, or form submission data"
        )
    write_csv("missing_utm_queue.csv", missing_utm, fieldnames=[
        "email", "company", "missing_fields", "lead_score",
        "data_quality_score", "recommended_fix",
    ])

    # ------------------------------------------------------------------
    # 8. low_enrichment_confidence_queue.csv  (clay_enrichment_confidence < 0.85)
    # ------------------------------------------------------------------
    low_confidence_rows: list[dict] = []
    for r in enriched:
        try:
            conf = float(r.get("clay_enrichment_confidence", 1.0))
        except (ValueError, TypeError):
            conf = 1.0
        if conf < 0.85:
            r["clay_enrichment_confidence"] = round(conf, 2)
            r["recommended_fix"] = (
                "Re-run Clay enrichment; manually verify company name, "
                "employee count, and industry before acting on lead score"
            )
            low_confidence_rows.append(r)
    write_csv("low_enrichment_confidence_queue.csv", low_confidence_rows, fieldnames=[
        "email", "company", "domain", "clay_enrichment_confidence",
        "lead_score", "data_quality_score", "revenue_leakage_risk", "recommended_fix",
    ])

    # ------------------------------------------------------------------
    # 9. routing_recommendations.csv
    # ------------------------------------------------------------------
    write_csv("routing_recommendations.csv", unique_leads_sorted, fieldnames=[
        "email", "company", "domain", "lead_score", "data_quality_score",
        "revenue_leakage_risk", "routing_recommendation", "next_best_action",
    ])

    # ------------------------------------------------------------------
    # 10. sync_issues.csv  — master QA issue table
    # One row per issue per contact (a contact can have multiple issues)
    # ------------------------------------------------------------------
    issues: list[dict] = []
    issue_counter = 1

    def add_issue(r, issue_type, severity, fix):
        nonlocal issue_counter
        issues.append({
            "issue_id":             f"ISS-{issue_counter:03d}",
            "email":                r.get("email", ""),
            "normalized_email":     r["normalized_email"],
            "company":              r.get("company", ""),
            "domain":               _val(r.get("domain")),
            "issue_type":           issue_type,
            "severity":             severity,
            "lead_score":           r["lead_score"],
            "data_quality_score":   r["data_quality_score"],
            "revenue_leakage_risk": r["revenue_leakage_risk"],
            "recommended_fix":      fix,
        })
        issue_counter += 1

    for r in enriched:
        ls = r["lead_score"]

        if not r["_in_sf"]:
            sev = "Critical" if ls >= 80 else ("High" if ls >= 60 else "Medium")
            add_issue(r, "HubSpot contact missing in Salesforce", sev,
                      "Create Salesforce lead; assign owner by routing segment; "
                      "set lifecycle stage to match HubSpot")

        if r["_in_sf"] and not _has_value(r.get("salesforce_owner")):
            sev = "Critical" if ls >= 80 else ("High" if ls >= 60 else "Medium")
            add_issue(r, "Salesforce lead missing owner", sev,
                      "Assign owner immediately based on industry segment")

        if r.get("_lifecycle_mismatch"):
            sev = "High" if ls >= 80 else "Medium"
            add_issue(r, "Lifecycle stage mismatch (HubSpot vs Salesforce)", sev,
                      f"Align HubSpot '{_val(r.get('lifecycle_stage'))}' with "
                      f"Salesforce '{_val(r.get('salesforce_lifecycle_stage'))}'")

        if r["_is_duplicate"]:
            add_issue(r, "Duplicate HubSpot contact by normalized email", "Medium",
                      "Merge duplicates in HubSpot; keep record with highest Data Quality Score")

        if not _has_value(r.get("utm_source")):
            sev = "Medium" if ls >= 60 else "Low"
            add_issue(r, "Missing utm_source", sev,
                      "Backfill from ad platform logs or CRM import history")

        if not _has_value(r.get("utm_campaign")):
            sev = "Medium" if ls >= 60 else "Low"
            add_issue(r, "Missing utm_campaign", sev,
                      "Backfill from ad platform logs or CRM import history")

        try:
            conf = float(r.get("clay_enrichment_confidence", 1.0))
        except (ValueError, TypeError):
            conf = 1.0
        if conf < 0.85:
            sev = "Medium" if ls >= 60 else "Low"
            add_issue(r, f"Low Clay enrichment confidence ({conf:.2f})", sev,
                      "Re-run Clay enrichment; verify firmographic data manually")

    write_csv("sync_issues.csv", issues, fieldnames=[
        "issue_id", "email", "normalized_email", "company", "domain",
        "issue_type", "severity", "lead_score", "data_quality_score",
        "revenue_leakage_risk", "recommended_fix",
    ])

    # ------------------------------------------------------------------
    # 11. hubspot_import_ready.csv
    # Original HubSpot contact fields + computed Vapi fields.
    # Use this file for HubSpot import — email is the contact key.
    # Unique leads only (duplicate-collapse rule applied).
    # ------------------------------------------------------------------
    for r in unique_leads_sorted:
        r["vapi_lead_score"]              = r.get("lead_score", "")
        r["vapi_data_quality_score"]      = r.get("data_quality_score", "")
        r["vapi_revenue_leakage_risk"]    = r.get("revenue_leakage_risk", "")
        r["vapi_routing_recommendation"]  = r.get("routing_recommendation", "")
        r["vapi_next_best_action"]        = r.get("next_best_action", "")

    write_csv("hubspot_import_ready.csv", unique_leads_sorted, fieldnames=[
        "email",
        "first_name",
        "last_name",
        "company",
        "domain",
        "job_title",
        "lifecycle_stage",
        "utm_source",
        "utm_campaign",
        "lead_source",
        "vapi_lead_score",
        "vapi_data_quality_score",
        "vapi_revenue_leakage_risk",
        "vapi_sync_health",
        "vapi_routing_recommendation",
        "vapi_next_best_action",
    ])

    # ------------------------------------------------------------------
    # salesforce_import_ready.csv
    # Salesforce Lead import file. Maps Vapi fields to custom SF fields.
    # Requires last_name, company, email on every row (SF minimum).
    # ------------------------------------------------------------------
    for r in unique_leads_sorted:
        r["vapi_intent_summary"] = _val(r.get("voice_ai_use_case"))
        r["vapi_use_case_fit"]   = _val(r.get("voice_ai_fit"))

    # ------------------------------------------------------------------
    # salesforce_existing_leads_import.csv  — 16 rows only
    #
    # Excludes the 3 leads intentionally absent from Salesforce
    # (Diana Torres, Linda Okafor, Nadia Volkov).
    # Those records are the hero artifact — importing them would fix
    # the leakage before the demo and break the reconciliation story.
    #
    # Import this file into Salesforce. Match by Email.
    # The 3 missing leads stay in high_intent_not_synced_to_salesforce.csv.
    # ------------------------------------------------------------------
    sf_existing = [
        r for r in unique_leads_sorted
        if r.get("vapi_sync_health") != "Not in Salesforce"
    ]
    write_csv("salesforce_existing_leads_import.csv", sf_existing, fieldnames=[
        "first_name",
        "last_name",
        "email",
        "company",
        "salesforce_status",
        "vapi_lead_score",
        "vapi_data_quality_score",
        "vapi_revenue_leakage_risk",
        "vapi_sync_health",
        "vapi_routing_recommendation",
        "vapi_next_best_action",
        "vapi_intent_summary",
        "vapi_use_case_fit",
    ])

    # ------------------------------------------------------------------
    # 12. reconciliation_summary.csv  — executive summary
    # ------------------------------------------------------------------
    critical_count = sum(1 for r in enriched if r["revenue_leakage_risk"] == "Critical")
    healthy_count  = sum(1 for r in enriched if r["revenue_leakage_risk"] == "Healthy")

    summary = [
        {"metric": "HubSpot contacts (total rows)",               "value": len(hs_rows)},
        {"metric": "Unique HubSpot contacts (by normalized email)","value": len(hs_by_email)},
        {"metric": "Salesforce leads",                             "value": len(sf_rows)},
        {"metric": "Clay enriched records",                        "value": len(clay_rows)},
        {"metric": "HubSpot contacts matched to Salesforce",      "value": len(hs_emails & sf_emails)},
        {"metric": "HubSpot contacts missing in Salesforce",      "value": len(hs_not_in_sf)},
        {"metric": "Salesforce leads missing in HubSpot",         "value": len(sf_not_in_hs)},
        {"metric": "Duplicate HubSpot contacts (by email)",       "value": len(duplicate_emails)},
        {"metric": "Salesforce leads missing owner",              "value": len(missing_owner)},
        {"metric": "Lifecycle stage mismatches",                   "value": len(lc_mismatches)},
        {"metric": "Records missing UTM attribution",              "value": len(missing_utm)},
        {"metric": "Low Clay enrichment confidence records",       "value": len(low_confidence_rows)},
        {"metric": "High-intent leads not in Salesforce",         "value": len(high_intent_not_synced)},
        {"metric": "Critical revenue leakage records",             "value": critical_count},
        {"metric": "Healthy records",                              "value": healthy_count},
    ]
    write_csv("reconciliation_summary.csv", summary, fieldnames=["metric", "value"])

    # -----------------------------------------------------------------------
    # Terminal output
    # -----------------------------------------------------------------------
    print(f"\n{'─' * 62}")
    print("  RECONCILIATION SUMMARY")
    print(f"{'─' * 62}")
    for row in summary:
        print(f"  {row['metric']:<45} {row['value']}")

    print(f"\n{'─' * 62}")
    print(f"  !! CRITICAL REVENUE LEAKAGE: {critical_count} record(s)")
    print(f"  High-intent leads NOT in Salesforce: {len(high_intent_not_synced)}")
    print(f"  (Lead Score >= 80, zero Salesforce visibility)")
    print(f"{'─' * 62}")

    if high_intent_not_synced:
        print("\n  TOP HIGH-INTENT LEADS NOT SYNCED TO SALESFORCE")
        print(f"  {'Company':<30} {'Score':>5}  {'Industry'}")
        print(f"  {'─'*30} {'─'*5}  {'─'*28}")
        for r in high_intent_not_synced[:5]:
            print(f"  {r['company']:<30} {r['lead_score']:>5}  {r.get('industry','')}")

    if missing_owner:
        print("\n  TOP MISSING-OWNER RECORDS")
        print(f"  {'Company':<30} {'Score':>5}  {'Risk'}")
        print(f"  {'─'*30} {'─'*5}  {'─'*12}")
        for r in missing_owner[:5]:
            print(f"  {r['company']:<30} {r['lead_score']:>5}  {r['revenue_leakage_risk']}")

    print(f"\n  Output files written to: data/output/")
    print(f"{'=' * 62}\n")


if __name__ == "__main__":
    main()
