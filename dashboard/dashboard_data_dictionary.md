# Dashboard Data Dictionary — Vapi GTM Reconciliation Engine

All dashboard views are built from the CSV files in `data/output/`. The files are flat, one row per record, ready for direct import into Power BI or Excel.

---

## Recommended dashboard views

### View 1 — Reconciliation Health (KPI cards)
**Source:** `reconciliation_summary.csv`

| Card | Metric name in CSV | What it shows |
|---|---|---|
| Total HubSpot contacts | HubSpot contacts (total rows) | Volume |
| Sync coverage | Records matched / HubSpot contacts | % of HubSpot contacts that reached Salesforce |
| Critical leakage | Critical revenue leakage records | Count of high-intent leads with structural failure |
| Missing owner | Missing Salesforce owner count | Routing gap count |
| Healthy records | Healthy records | Baseline for comparison |

---

### View 2 — High-Intent Leads Not Synced to Salesforce *(hero view)*
**Source:** `high_intent_not_synced_to_salesforce.csv`

| Column | Type | Description |
|---|---|---|
| `email` | Text | Contact email |
| `company` | Text | Company name |
| `lead_score` | Number | Lead Score (0–100) |
| `industry` | Text | ICP vertical |
| `active_job_signal` | Text | Yes/No — hiring CX/support roles |
| `intent_summary` | Text | Clay-generated outreach angle |
| `business_risk` | Text | Risk label |
| `recommended_fix` | Text | Action for RevOps |

Sort by `lead_score` descending. This table is the primary proof of revenue leakage.

---

### View 3 — Sync Issues by Severity
**Source:** `sync_issues.csv`

Recommended: stacked bar chart — x-axis is `issue_type`, bars stacked by `severity` (Critical, High, Medium, Low).

| Column | Type | Description |
|---|---|---|
| `issue_type` | Text | Category of problem |
| `severity` | Text | Critical / High / Medium / Low |
| `lead_score` | Number | Used to size/color markers |
| `recommended_fix` | Text | Tooltip on hover |

---

### View 4 — Missing Owner Queue
**Source:** `missing_owner_queue.csv`

Table sorted by `lead_score` descending. Show `revenue_leakage_risk` as a color-coded badge column.

| Column | Description |
|---|---|
| `company` | Company name |
| `lead_score` | Priority signal |
| `revenue_leakage_risk` | Critical / Medium / Low |
| `suggested_routing_segment` | Regulated Industries / Operations / Platform |
| `action_required` | Always "Assign owner" |

---

### View 5 — Lead Score Distribution
**Source:** `scored_leads.csv`

Histogram of `lead_score`. Recommended buckets: 0–39, 40–59, 60–79, 80–100. Color code: 80–100 = red/urgent, 60–79 = amber, below 60 = grey.

---

### View 6 — Routing Recommendation Breakdown
**Source:** `routing_recommendations.csv`

Donut or bar chart. Group by `routing_recommendation` value.

| Value | Meaning |
|---|---|
| AE Priority | Score ≥ 80, synced, owned, no critical issues |
| RevOps Critical Fix before Sales Follow-Up | Score ≥ 80, not in Salesforce |
| Assign Owner Immediately | Score ≥ 80, missing owner |
| Fix Lifecycle Before Routing | Score ≥ 80, lifecycle mismatch |
| SDR Priority | Score 60–79, synced |
| Nurture | Score 40–59 |
| Hold / Enrich Further | Score < 40 |

---

## Field types for Power BI import

All numeric fields (`lead_score`, `data_quality_score`, `clay_enrichment_confidence`, `duplicate_count`) should be imported as **Whole Number** or **Decimal Number** — not Text.

`last_activity_date` fields are formatted `YYYY-MM-DD` — import as **Date**.

All other fields are **Text**.

---

## Note on the "not synced to Salesforce" view

There is no Salesforce list view for records not synced to Salesforce — those records do not exist in Salesforce. The leakage view must be built from `high_intent_not_synced_to_salesforce.csv`. This is intentional. In a live system, this file would be refreshed nightly and displayed on the dashboard alongside the Salesforce-sourced views.
