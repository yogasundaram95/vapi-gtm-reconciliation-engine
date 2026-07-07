# Vapi GTM Reconciliation Engine

A mock-data reconciliation monitor that compares a HubSpot contact export against a Salesforce lead export, joins Clay-style enrichment signals by company domain, and prioritizes GTM issues by revenue impact.

---

## Why I built this

During the interview, a few real operational problems came up: HubSpot and Salesforce not syncing cleanly, leads landing without owners, lifecycle stages disagreeing between systems, and Clay enrichment that only works if the underlying CRM data is trustworthy.

I built a working prototype that detects those problems, ranks them by revenue risk, and produces actionable queues for RevOps and Sales.

---

## The GTM problem

Marketing generates contacts in HubSpot. Sales works leads in Salesforce. The sync between them leaks. Specifically:

- High-intent HubSpot contacts never become Salesforce leads — Sales never sees them
- Leads that do cross over often have no owner, so nobody works them
- Lifecycle stages in HubSpot and lead status in Salesforce disagree, creating routing confusion
- UTM attribution is missing on a significant share of records, breaking campaign reporting
- Duplicate contacts inflate pipeline counts and split engagement history
- Clay enrichment confidence is low on some accounts, making scores unreliable

The result is revenue leakage. High-value leads sit invisible to Sales while the team works lower-priority records.

---

## What the engine does

1. Loads three export files: HubSpot contacts, Salesforce leads, Clay-style enrichment
2. Normalizes emails (lowercase, trimmed) as the contact-level join key
3. Joins Clay enrichment separately by company domain — account-level data, not contact-level identity
4. Detects duplicates by normalized email only — two people at the same company are not duplicates
5. Scores each lead across three separate axes: Lead Score, Data Quality Score, Revenue Leakage Risk
6. Classifies and prioritizes every structural gap
7. Outputs reconciliation queues and scored datasets as CSV files
8. Feeds the final Looker Studio dashboard; an optional Excel workbook is also available

This is not live sync. It is the logic a nightly reconciliation job would run against CRM exports to surface problems before they become missed revenue.

---

## Architecture

```
HubSpot contacts export       Salesforce leads export       Clay enrichment export
(hubspot_contacts.csv)        (salesforce_leads.csv)        (clay_enrichment_mock.csv)
         |                             |                              |
         |_____________________________|                              |
                      |                                              |
         Join on normalized email (contact level)         Join on domain (account level)
                      |______________________________________________|
                                       |
                              src/reconcile.py
                                       |
                    ┌──────────────────┼──────────────────┐
                    |                  |                   |
             scoring_rules.py    Issue detection     Risk classification
             Lead Score          Sync gaps           Revenue Leakage Risk
             Data Quality Score  Missing owners      Routing recommendation
                    |                  |                   |
                    └──────────────────┼───────────────────┘
                                       |
                              data/output/
                    ┌──────────────────┼──────────────────┐
                    |                  |                   |
            reconciliation_    high_intent_not_    missing_owner_
            summary.csv        synced_to_salesforce.csv   queue.csv
                                   (hero)
                            + 8 other output CSVs
                                       |
                              Looker Studio dashboard
```

---

## Reconciliation logic

### Record matching

HubSpot contacts and Salesforce leads are matched using:

`normalized_email = email.strip().lower()`

This is the only contact-level matching and deduplication key.

Clay-style enrichment is joined separately by normalized company domain because it represents account-level enrichment, not person-level identity.

### Duplicate detection
A duplicate is two HubSpot records with the same normalized email. Two different people at the same company with different emails are not duplicates. Domain-based deduplication is explicitly excluded.

### Lifecycle mismatch detection
The engine maps HubSpot lifecycle stages to expected Salesforce lifecycle stage equivalents. A mismatch is flagged when the two systems place the same contact at different funnel stages — for example, HubSpot shows `Marketing Qualified Lead` while Salesforce shows `Lead`.

### Sync gap detection
A contact is flagged as missing from Salesforce when no Salesforce lead record matches its normalized email. High-intent contacts (Lead Score ≥ 80) that fail this check are promoted to Critical revenue leakage.

---

## Lead Score vs Data Quality Score vs Revenue Leakage Risk

These are three separate axes. They are never blended.

| Score | What it measures | Max |
|---|---|---|
| Lead Score | Lead value: fit, intent, engagement, hiring signal | 100 |
| Data Quality Score | Field completeness only | 100 |
| Revenue Leakage Risk | Structural GTM risk using Lead Score + sync/owner/lifecycle facts | Critical / High / Medium / Low / Healthy |

**Lead Score breakdown:**

| Dimension | Max | Key signals |
|---|---|---|
| Fit | 35 | ICP industry, employee count 100–5,000, voice AI use case fit, relevant tech stack |
| Intent | 30 | Pricing/demo page visits, docs/API page visits, API key created, test call count |
| Engagement | 20 | Demo form submitted, campaign reply, booked demo |
| Hiring Signal | 15 | CX/support/ops job posted within 14 days (15 pts), 30 days (10 pts), older (5 pts) |

The Intent dimension includes PLG signals (docs visits, API key creation, test calls) because Vapi is a developer-first platform where product exploration precedes purchase.

**Data Quality Score** covers field completeness only: email, domain, company, job title, lifecycle stage, UTM source, UTM campaign, lead source, Clay enrichment confidence ≥ 0.85, and recent activity date. Owner and sync status are excluded — those belong in Revenue Leakage Risk, not completeness.

**Why keep them separate?** A high-fit lead with a missing UTM field should be escalated for enrichment, not buried. Blending scores would hide exactly the records RevOps needs to find.

**Revenue Leakage Risk classification:**

| Risk | Condition |
|---|---|
| Critical | Lead Score ≥ 80 AND (missing from Salesforce OR missing Salesforce owner) |
| High | Lead Score ≥ 80 AND (lifecycle mismatch OR duplicate email) |
| Medium | Lead Score ≥ 60 AND (missing UTM OR enrichment confidence < 0.85) |
| Low | Lead Score < 60 with a minor structural issue |
| Healthy | Synced, owned, lifecycle aligned, no duplicate, attribution intact |

---

## Key findings

The source data contains 20 HubSpot rows (19 unique by normalized email) and 18 Salesforce rows. Of those, 16 contacts match across both systems, 3 HubSpot contacts are missing from Salesforce, and 2 Salesforce records have no matching HubSpot contact.

For the live Salesforce demo environment, I imported the 16 matched leads only and intentionally excluded the 3 HubSpot-only leads so the reconciliation gap remained visible.

| Metric | Count |
|---|---|
| HubSpot contacts matched to Salesforce | 16 |
| **High-intent leads not in Salesforce** | **3** |
| Critical revenue leakage records | 4 |
| Salesforce leads missing owner | 6 |
| Lifecycle stage mismatches | 4 |
| Records missing UTM attribution | 10 |
| Duplicate HubSpot contacts (by email) | 1 group |
| Low Clay enrichment confidence | 10 |
| Healthy records | 5 |

**The 3 high-intent leads not in Salesforce:**

| Company | Lead Score | Industry |
|---|---|---|
| FreightLink Logistics | 96 | Logistics |
| SupportNova | 96 | Customer Support SaaS |
| SafeGuard Insurance | 84 | Insurance |

These are mock HubSpot contacts designed with strong fit, intent, engagement, and hiring signals. In the simulated workflow, Salesforce has no matching record for them. That is the type of leakage this engine is built to surface.

---

## HubSpot and Salesforce proof

**HubSpot (free tier):**
- 7 custom contact properties created: Vapi Lead Score, Vapi Data Quality Score, Vapi Revenue Leakage Risk, Vapi Sync Health, Vapi Routing Recommendation, Vapi Next Best Action, Vapi Intent Summary
- 19 contacts imported with computed fields populated
- `vapi_sync_health` values include: Synced - Healthy, Synced - Missing Owner, Synced - Stage Mismatch, Synced - Missing UTM, Not in Salesforce, Duplicate Contact

**Salesforce (Developer Edition):**
- 7 custom Lead fields created matching the HubSpot properties
- 16 demo leads imported — the 3 intentionally missing leads were excluded to preserve the demo state
- 5 list views built: Vapi Synced High Priority Leads, Vapi Missing Owner, Vapi Stage Mismatch, Vapi Duplicate Contacts, Vapi All Synced Leads
- Lead record detail view shows all Vapi custom fields populated

The 3 missing leads — Diana Torres, Linda Okafor, Nadia Volkov — were deliberately kept out of Salesforce. Importing them would have invalidated the reconciliation demo.

---

## Dashboard

Built in Looker Studio from the reconciliation output CSVs.

**KPI cards:**
- 19 Unique HubSpot Contacts
- 16 Matched Salesforce Leads
- 3 High-Intent Leads Missing from Salesforce
- 4 Critical Revenue Leakage Records

**Issue chart — 7 issue types grouped into 3 GTM impact categories:**

| GTM Category | Issue | Count |
|---|---|---|
| Data Quality | Low Clay enrichment confidence | 10 |
| Funnel Visibility | Missing `utm_campaign` | 7 |
| Revenue Leakage | Lifecycle stage mismatch | 4 |
| Funnel Visibility | Missing `utm_source` | 4 |
| Revenue Leakage | HubSpot contact missing in Salesforce | 3 |
| Revenue Leakage | Salesforce lead missing owner | 3 |
| Data Quality | Duplicate HubSpot contact by normalized email | 2 |

**Hero table:** The 3 high-intent leads missing from Salesforce, with company, email, lead score, intent summary, active job signal, and recommended fix.

---

## Limitations

- **Not live sync.** This engine runs on CSV exports. It does not connect to HubSpot or Salesforce APIs.
- **Clay is mocked.** The enrichment schema is designed to match real Clay output columns, but the values are fictional. No live Clay API was called.
- **Mock data only.** All company names and contacts are fictional. This project does not touch Vapi's production systems or real prospect data.
- **Scoring weights are not validated.** The Lead Score rules are defensible by design logic, but have not been back-tested against closed-won data.
- **"Recent activity within 7 days" scores 0 in the demo** because the mock data uses 2024 dates. In a live system this signal would differentiate active leads in real time.

---

## How I would productionize this

1. **Replace CSV ingestion with API connectors** — use the HubSpot Contacts API and Salesforce API while preserving the same downstream reconciliation and scoring logic. Production connectors would also require authentication, pagination, rate-limit handling, retries, and schema validation.
2. **Connect live Clay enrichment** — trigger Clay on new or updated HubSpot contacts via webhook; receive enrichment output and join by domain.
3. **Schedule nightly reconciliation** — Power Automate scheduled flow or a cron job running at 2 AM; writes results back to both CRMs.
4. **Slack alert for Critical leakage** — when new Critical records appear in the engine output, send a Slack message to RevOps and Sales channels with company, lead score, and recommended action.
5. **Write sync health back to CRMs** — update `Vapi Sync Health` on HubSpot contacts and Salesforce leads after each run so both systems reflect current reconciliation state.
6. **Historical score validation** — join Lead Score output against Salesforce closed-won deals over time; tune dimension weights based on what actually converts.
7. **Parameterize thresholds** — move score cutoffs (80 for Critical, 60 for Medium, 0.85 for enrichment confidence) to a config file so RevOps can tune without touching code.

---

## Repository structure

```
vapi_gtm_reconciliation_engine/
├── README.md
├── requirements.txt
├── architecture.md
├── implementation_notes.md
├── src/
│   ├── reconcile.py              — core reconciliation engine
│   ├── scoring_rules.py          — Lead Score and Data Quality Score logic
│   └── create_dashboard.py       — generates Excel workbook from output CSVs
├── sql/
│   └── reconciliation_queries.sql — SQL reference for the same scoring logic
├── data/
│   ├── input/
│   │   ├── hubspot_contacts.csv
│   │   ├── salesforce_leads.csv
│   │   └── clay_enrichment_mock.csv
│   └── output/
│       ├── reconciliation_summary.csv
│       ├── sync_issues.csv
│       ├── high_intent_not_synced_to_salesforce.csv   ← hero artifact
│       ├── missing_owner_queue.csv
│       ├── lifecycle_mismatch_queue.csv
│       ├── duplicate_contacts.csv
│       ├── missing_utm_queue.csv
│       ├── low_enrichment_confidence_queue.csv
│       ├── scored_leads.csv
│       ├── data_quality_scores.csv
│       ├── routing_recommendations.csv
│       ├── hubspot_import_ready.csv
│       ├── salesforce_existing_leads_import.csv
│       └── salesforce_encoding_fix.csv
├── dashboard/
│   ├── vapi_reconciliation_dashboard.xlsx
│   └── dashboard_data_dictionary.md
└── screenshots/
    └── screenshot_checklist.md
```

---

## How to run locally

**Requirements:** Python 3.10+, no external packages for the core engine.

```bash
cd vapi_gtm_reconciliation_engine

# Run the reconciliation engine
python3 src/reconcile.py
```

Terminal prints the reconciliation summary, critical leakage count, top high-intent leads not in Salesforce, and top missing-owner records. All output CSVs are written to `data/output/`.

```bash
# Optional: generate the Excel workbook
pip3 install openpyxl
python3 src/create_dashboard.py
```

The Excel workbook is written to `dashboard/vapi_reconciliation_dashboard.xlsx`.

---

*Built with Python, HubSpot free tier, Salesforce Developer Edition, Looker Studio, and Claude Code.*
*All data is fictional. This project does not connect to or represent Vapi's production systems.*
