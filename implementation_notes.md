# Implementation Notes — Vapi GTM Reconciliation Engine

## Build approach

This project was built as a mock-data demonstration of the reconciliation and scoring logic I would run in a real HubSpot/Salesforce/Clay environment. The engine is structured so that swapping the CSV exports for live API calls is a mechanical change, not a redesign.

Claude Code was used to scaffold the repo and write the initial Python scripts. All scoring weights, field definitions, issue-type logic, and routing rules were designed by me based on the business problem described in the interview.

---

## Key design decisions

### 1. Three separate scores, never blended

The spec review identified a common mistake in lead scoring systems: blending data quality into lead score. This buries high-value leads with incomplete records. The engine separates:

- **Lead Score** — measures lead value. Never penalized for missing fields.
- **Data Quality Score** — measures field completeness. Never affects routing directly.
- **Revenue Leakage Risk** — uses Lead Score plus structural facts (sync, owner, lifecycle, duplicates). Not a score; a classification.

### 2. Normalized email as the only join key

Domain-level matching was explicitly excluded. Two people at the same company are not duplicates. The join runs on `email.strip().lower()`. This prevents false-positive duplicate flags that would hide real contacts.

### 3. Duplicate-collapse rule is deterministic

When the same normalized email appears more than once in HubSpot (true duplicates), unique-lead outputs (`scored_leads.csv`, `data_quality_scores.csv`) keep the record with the highest Data Quality Score. Tie-break: most recent `last_activity_date`. This rule is documented in README.md and enforced in `reconcile.py` (`best_by_email` dict). The behavior is deterministic and testable.

### 4. No fabricated owner names

The missing-owner queue includes `suggested_routing_segment` based on the deterministic industry-to-segment map. It does not invent individual person names (like "SDR East" or "AE 1") because no territory map was provided. In a real deployment, this would be replaced with a lookup against the Salesforce user directory or a territory mapping table.

### 5. PLG intent signals are Vapi-specific

The Intent dimension of Lead Score includes `docs_page_visits`, `api_docs_visits`, `api_key_created`, and `test_call_count`. These are Vapi-specific product-led growth signals that a traditional B2B lead scoring model would not have. They reflect that Vapi is a developer-first voice API platform where self-serve product exploration is a strong buying signal.

### 6. Lifecycle stage mismatch is directional

The engine detects mismatches where HubSpot lifecycle stage implies higher funnel stage than Salesforce lead status reflects. For example, a contact marked "Sales Qualified Lead" in HubSpot but "New" in Salesforce means Sales is not seeing the qualification signal. The mismatch map in `reconcile.py` (`LIFECYCLE_TO_SF_STATUS`) defines expected Salesforce status values for each HubSpot stage.

---

## What to expect in each output

### `high_intent_not_synced_to_salesforce.csv`

This is the most important output for a hiring manager review. It directly answers: "Which high-value leads does Sales not know exist?" Every row is a lead that scored 80+ on fit, intent, engagement, and hiring signal but has zero Salesforce visibility. In a live system this file triggers an immediate alert.

### `sync_issues.csv`

The full issue log. Each row is one detected problem for one contact. A single contact can appear multiple times if it has multiple issues (e.g., missing from Salesforce AND missing UTM). This is intentional — each issue is a separate recommended action. The `issue_id` column makes it easy to track remediation.

### `reconciliation_summary.csv`

15-metric summary designed for a Power BI KPI card view or an executive Slack digest. Metrics include sync coverage rate, healthy record count, critical leakage count, and UTM attribution coverage.

---

## Seeded defects and what catches them

| Defect | Contacts affected | Detected in |
|---|---|---|
| HubSpot contact missing in Salesforce | diana.torres (FreightLink), linda.okafor (SafeGuard), nadia.volkov (SupportNova), amara.obi (FieldSpark) | `sync_issues.csv`, `high_intent_not_synced_to_salesforce.csv` |
| High-intent leads missing in Salesforce | diana.torres (96), nadia.volkov (91), linda.okafor (84) | `high_intent_not_synced_to_salesforce.csv` |
| Missing Salesforce owner | james.whitfield, linda.okafor, kevin.osei, yuki.tanaka, elena.vasquez, nadia.volkov, diana.torres, amara.obi, and others | `missing_owner_queue.csv` |
| Lifecycle mismatch | marcus.chen (MQL in HS, New in SF), kevin.osei (Lead in HS, SQL in SF), raj.sharma (Lead in HS, Working in SF) | `lifecycle_mismatch_queue.csv` |
| Duplicate HubSpot contact | kevin.osei@marketnest.com (HS006 + HS012) | `duplicate_contacts.csv` |
| Missing UTM | Multiple records | `missing_utm_queue.csv` |
| Low enrichment confidence | 10 records below 0.85 threshold | `low_enrichment_confidence_queue.csv` |

---

## How I would extend this in a real rollout

1. **Replace CSV reads with API calls** — HubSpot Contacts API (v3) and Salesforce Bulk API. The `read_csv()` function in `reconcile.py` is the only thing that changes.
2. **Add historical scoring validation** — join `scored_leads.csv` against Salesforce closed-won deals. Check whether Lead Score >= 80 records closed at a higher rate. Tune weights accordingly.
3. **Add a confidence interval to scores** — when enrichment confidence is low, flag scores as "approximate" rather than precise. Avoids routing decisions based on unreliable inputs.
4. **Parameterize thresholds** — score thresholds (80 for Critical, 60 for Medium, 0.85 for enrichment confidence) should be environment variables or a config file, not constants in code.
5. **Write sync status back to HubSpot** — after each reconciliation run, update the `Sync Status` custom property on each HubSpot contact so Marketing can see which contacts reached Salesforce.
