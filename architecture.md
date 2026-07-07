# Architecture — Vapi GTM Reconciliation Engine

## Data flow

```
┌─────────────────────┐    ┌──────────────────────┐    ┌─────────────────────────┐
│  HubSpot Contacts   │    │  Salesforce Leads     │    │  Clay Enrichment        │
│  (CSV export)       │    │  (CSV export)         │    │  (mocked CSV output)    │
│                     │    │                       │    │                         │
│  20 contacts        │    │  15 lead records      │    │  19 enriched records    │
│  custom properties  │    │  custom fields        │    │  firmographics, signals │
└────────┬────────────┘    └──────────┬────────────┘    └────────────┬────────────┘
         │                           │                               │
         └──────────────────┬────────┘                               │
                            │ join on normalized email                │
                            ▼                                        │
              ┌─────────────────────────────┐                        │
              │   reconcile.py              │◄───────────────────────┘
              │                             │   merge enrichment fields
              │  1. Merge all three sources │
              │  2. Flag structural issues  │
              │  3. Score each lead         │
              │  4. Classify leakage risk   │
              │  5. Assign routing          │
              └──────────────┬──────────────┘
                             │
              ┌──────────────▼──────────────┐
              │       scoring_rules.py       │
              │                             │
              │  Lead Score (fit/intent/     │
              │    engagement/hiring)        │
              │  Data Quality Score          │
              │  Revenue Leakage Risk        │
              │  Routing Recommendation      │
              └──────────────┬──────────────┘
                             │
         ┌───────────────────▼──────────────────────┐
         │            data/output/                   │
         │                                           │
         │  reconciliation_summary.csv               │
         │  sync_issues.csv                          │
         │  high_intent_not_synced_to_sf.csv  ◄──── │── hero artifact
         │  missing_owner_queue.csv                  │
         │  lifecycle_mismatch_queue.csv             │
         │  duplicate_contacts.csv                   │
         │  missing_utm_queue.csv                    │
         │  low_enrichment_confidence_queue.csv      │
         │  scored_leads.csv                         │
         │  data_quality_scores.csv                  │
         │  routing_recommendations.csv              │
         └───────────────────────────────────────────┘
                             │
                             ▼
              ┌──────────────────────────┐
              │  Power BI / Excel        │
              │  dashboard               │
              │                          │
              │  5-6 views from          │
              │  output CSVs             │
              └──────────────────────────┘
```

## Join key

All three sources are joined on **normalized email** — `email.strip().lower()`.

This is the only deduplication key. Two contacts at the same domain are not duplicates unless their normalized emails match exactly.

## Score isolation

```
Lead Score (100)
├── Fit Score (35)          → industry, employee count, voice AI fit, tech stack
├── Intent Score (30)       → pricing/demo/docs/API page, API key, test calls, recency
├── Engagement Score (20)   → demo form, campaign reply, booked demo
└── Hiring Signal (15)      → CX/support/dev rel job posting recency

Data Quality Score (100)    → field completeness only (email, domain, company,
                              job title, lifecycle, UTM, lead source, activity date)

Revenue Leakage Risk        → Lead Score + structural facts only
(Critical/High/Med/Low/     (sync status, owner presence, lifecycle mismatch,
 Healthy)                    duplicate flag, UTM missing, enrichment confidence)
```

**These three scores never share inputs.** Enrichment confidence, owner, and sync status appear only in Revenue Leakage Risk. Field presence appears only in Data Quality Score.

## Productionization path

| Step | Tool | Notes |
|---|---|---|
| Pull HubSpot contacts | HubSpot API v3 | Incremental sync using `lastmodifieddate` filter |
| Pull Salesforce leads | Salesforce Bulk API | SOQL query for changed records since last run |
| Pull Clay enrichment | Clay webhook | Fire on new/updated HubSpot contact |
| Schedule reconciliation | Power Automate | Nightly scheduled flow; on-demand trigger for RevOps |
| Alert on Critical leakage | Slack via webhook | Notify RevOps + Sales channel |
| Write results back to CRMs | HubSpot/SF API | Update `Sync Status`, `Revenue Leakage Risk`, `Routing Recommendation` |
| Dashboard | Power BI | Direct connection to Salesforce; import for HubSpot/Clay CSVs |
