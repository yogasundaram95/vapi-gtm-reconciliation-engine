# Loom Walkthrough Script — Vapi GTM Reconciliation Engine

Target length: 3–4 minutes. Keep delivery calm and plain. Do not narrate every field.

---

## 0:00 – 0:20 — Disclaimer and framing

> "Thanks again for the conversation earlier. Quick disclaimer before I show anything: this is not a live sync, and I did not touch Vapi's systems. This is a mock-data reconciliation monitor that shows the logic I would use to detect lead leakage, owner gaps, lifecycle mismatches, duplicate records, and missing attribution. Everything here uses fictional companies. Let me show you how it works."

---

## 0:20 – 0:45 — The business problem

> "The problem this solves is specific: HubSpot and Salesforce don't stay in sync cleanly. Qualified leads get created in HubSpot but never land in Salesforce, so Sales never sees them. When they do cross over, they often have no owner, so nobody works them. Lifecycle stages disagree between the two systems. Attribution data is missing. And duplicate contacts inflate the pipeline count. The result is revenue leakage. This engine makes it visible."

---

## 0:45 – 1:10 — Clay enrichment schema

*Screen: `clay_enrichment_mock.csv` open in a spreadsheet*

> "Enrichment starts here. I designed this Clay table to capture the signals that actually matter for Vapi's ICP: firmographics, whether the company already runs an IVR or contact center stack, whether they're actively hiring for CX or support roles, a voice AI fit tier, and an enrichment confidence score. The values in this file are mocked for the demo. The schema is what I'd actually run in Clay."

---

## 1:10 – 1:30 — HubSpot custom properties

*Screen: HubSpot Settings > Properties > Contacts showing custom fields*

> "In HubSpot I created custom properties to hold the outputs of this engine: Lead Score, Data Quality Score, Voice AI Fit, Routing Recommendation, Sync Status, and Revenue Leakage Risk. These live on each contact record and give Marketing visibility into sync health without needing to open Salesforce."

---

## 1:30 – 2:30 — The Python engine *(spend the most time here)*

*Screen: VS Code with `reconcile.py` open, then switch to terminal*

> "Here's the core of the project. The engine loads the three exports, joins them on normalized email — lowercase, trimmed, exact match only — and then runs three separate scoring passes."

> "Lead Score measures lead value: fit to ICP, product intent signals, engagement, and hiring signal. For Vapi specifically, I included PLG signals: docs page visits, API docs visits, API key created, and test calls. Those are stronger buying signals for a developer-first platform than email opens."

> "Data Quality Score measures field completeness only. It never affects Lead Score. A high-fit lead with a missing UTM field should be escalated for enrichment, not buried. That's why the scores are separate."

> "Revenue Leakage Risk combines Lead Score with structural facts: is the record in Salesforce, does it have an owner, is the lifecycle stage aligned, are there duplicate emails. That's the classification that drives routing."

*Switch to terminal, run `python3 src/reconcile.py`*

> "When I run it: 20 HubSpot contacts, 15 Salesforce leads, 4 contacts missing entirely from Salesforce — 3 of those scored above 80. That means 3 high-intent leads have zero Salesforce visibility. Sales never sees them. That's the leakage number."

---

## 2:30 – 2:50 — Salesforce custom fields and list views

*Screen: Salesforce Lead list views*

> "In Salesforce I built matching custom fields and four list views. SDR Fast-Track: score above 80, owner assigned. Missing Owner Queue: owner blank. High Score, No Owner: the most expensive gap. Data Quality Cleanup: for RevOps to work through. The one thing you won't see is a list view for 'not synced to Salesforce' — those records don't exist in Salesforce, so no SF view can show them. That queue lives in the output CSV and the dashboard."

---

## 2:50 – 3:20 — Dashboard

*Screen: Power BI or Excel dashboard*

> "The dashboard pulls from the output CSVs. KPI cards at the top show sync coverage, critical leakage count, and healthy record count. The view that matters most is this one: high-intent leads not in Salesforce. Three companies, top lead score 96, all invisible to Sales right now. In a live system this triggers an immediate alert. The other views show sync issues by severity, lead score distribution, and routing breakdown."

---

## 3:20 – 3:40 — Close

> "To productionize this, I'd replace the CSV reads with HubSpot and Salesforce API calls, schedule it nightly via Power Automate, add a Slack alert when new Critical records appear, and write the sync status back to both CRMs after each run. The scoring weights and thresholds are all parameterized so they can be tuned against closed-won data over time. That's the engine — happy to go deeper on any part of it."

---

## Notes for recording

- Keep screen resolution high enough that CSV column headers are readable
- Run the terminal live during recording — do not use a pre-recorded clip
- Show the output folder in Finder after the terminal run to demonstrate all 11 files were generated
- Do not use the hiring manager's first name unless confirmed
- Do not use the words "AI-powered," "innovative," or "cutting-edge" anywhere
