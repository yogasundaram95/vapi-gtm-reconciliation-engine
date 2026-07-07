-- reconciliation_queries.sql
-- Vapi GTM Reconciliation Engine
--
-- SQL reference expressing the same scoring and reconciliation logic
-- from scoring_rules.py and reconcile.py.
-- These queries are written for readability and portability (standard SQL).
-- Run against scored_leads.csv and sync_issues.csv loaded into a SQL table,
-- or adapt for Salesforce SOQL / HubSpot custom reporting.

-- ============================================================
-- 1. LEAD SCORE — component breakdown
-- ============================================================

SELECT
    email,
    company,
    industry,
    employee_count,

    -- Fit Score (max 35)
    CASE WHEN LOWER(industry) IN (
        'healthcare','insurance','logistics','home services','field services',
        'marketplace','tax software','customer support-heavy saas',
        'call center-heavy operations','developer/api-first'
    ) THEN 10 ELSE 0 END
    +
    CASE WHEN CAST(employee_count AS INT) BETWEEN 100 AND 5000 THEN 10 ELSE 0 END
    +
    CASE
        WHEN LOWER(clay_voice_ai_fit) = 'high'   THEN 10
        WHEN LOWER(clay_voice_ai_fit) = 'medium' THEN 5
        ELSE 0
    END
    +
    CASE WHEN LOWER(clay_tech_stack) LIKE '%ivr%'
          OR LOWER(clay_tech_stack) LIKE '%genesys%'
          OR LOWER(clay_tech_stack) LIKE '%five9%'
          OR LOWER(clay_tech_stack) LIKE '%avaya%'
          OR LOWER(clay_tech_stack) LIKE '%twilio%'
          OR LOWER(clay_tech_stack) LIKE '%contact center%'
          OR LOWER(clay_tech_stack) LIKE '%call center%'
         THEN 5 ELSE 0 END
    AS fit_score,

    -- Intent Score (max 30)
    CASE WHEN viewed_pricing_page = 'yes' OR CAST(pricing_page_visits AS INT) > 0
          OR viewed_demo_page = 'yes' OR CAST(demo_page_visits AS INT) > 0
         THEN 10 ELSE 0 END
    +
    CASE WHEN CAST(docs_page_visits AS INT) > 0
          OR CAST(api_docs_visits AS INT) > 0
         THEN 8 ELSE 0 END
    +
    CASE WHEN api_key_created = 'yes'
          OR CAST(test_call_count AS INT) > 0
         THEN 8 ELSE 0 END
    -- recent activity within 7 days omitted here (requires date arithmetic)
    AS intent_score_partial,

    -- Engagement Score (max 20)
    CASE WHEN demo_form_submitted = 'yes' THEN 8 ELSE 0 END
    + CASE WHEN campaign_reply = 'yes' THEN 6 ELSE 0 END
    + CASE WHEN booked_demo = 'yes' THEN 6 ELSE 0 END
    AS engagement_score,

    -- Hiring Signal Score (max 15)
    CASE
        WHEN LOWER(clay_hiring_cx) = 'yes' AND CAST(clay_job_signal_cx_days AS INT) <= 14 THEN 15
        WHEN LOWER(clay_hiring_cx) = 'yes' AND CAST(clay_job_signal_cx_days AS INT) <= 30 THEN 10
        WHEN LOWER(clay_hiring_cx) = 'yes' THEN 5
        WHEN LOWER(clay_job_signal_type) LIKE '%adjacent%' THEN 5
        ELSE 0
    END AS hiring_signal_score

FROM hubspot_contacts;


-- ============================================================
-- 2. DATA QUALITY SCORE — completeness only
-- ============================================================

SELECT
    email,
    company,
    100
    - CASE WHEN email IS NULL OR TRIM(email) = '' THEN 20 ELSE 0 END
    - CASE WHEN domain IS NULL OR TRIM(domain) = '' THEN 10 ELSE 0 END
    - CASE WHEN company IS NULL OR TRIM(company) = '' THEN 10 ELSE 0 END
    - CASE WHEN job_title IS NULL OR TRIM(job_title) = '' THEN 10 ELSE 0 END
    - CASE WHEN hs_lifecyclestage IS NULL OR TRIM(hs_lifecyclestage) = '' THEN 15 ELSE 0 END
    - CASE WHEN utm_source IS NULL OR TRIM(utm_source) = '' THEN 10 ELSE 0 END
    - CASE WHEN utm_campaign IS NULL OR TRIM(utm_campaign) = '' THEN 10 ELSE 0 END
    - CASE WHEN lead_source IS NULL OR TRIM(lead_source) = '' THEN 5 ELSE 0 END
    - CASE WHEN last_activity_date IS NULL OR TRIM(last_activity_date) = '' THEN 10 ELSE 0 END
    AS data_quality_score

FROM hubspot_contacts;


-- ============================================================
-- 3. REVENUE LEAKAGE RISK classification
-- ============================================================

SELECT
    h.email,
    h.company,
    h.lead_score,
    CASE
        WHEN h.lead_score >= 80 AND (s.email IS NULL OR TRIM(s.sf_owner) = '') THEN 'Critical'
        WHEN h.lead_score >= 80 AND (lm.email IS NOT NULL OR d.email IS NOT NULL) THEN 'High'
        WHEN h.lead_score >= 60 AND (
            TRIM(h.utm_source) = '' OR TRIM(h.utm_campaign) = ''
            OR CAST(c.clay_enrichment_confidence AS FLOAT) < 0.85
        ) THEN 'Medium'
        WHEN h.lead_score < 60 THEN 'Low'
        ELSE 'Healthy'
    END AS revenue_leakage_risk

FROM scored_leads h
LEFT JOIN salesforce_leads s
    ON LOWER(TRIM(h.email)) = LOWER(TRIM(s.email))
LEFT JOIN (
    -- Lifecycle mismatch subquery
    SELECT LOWER(TRIM(h2.email)) AS email
    FROM hubspot_contacts h2
    JOIN salesforce_leads s2 ON LOWER(TRIM(h2.email)) = LOWER(TRIM(s2.email))
    WHERE
        (LOWER(h2.hs_lifecyclestage) = 'sales qualified lead'
         AND LOWER(s2.sf_lead_status) NOT IN ('working','sql','sales qualified lead'))
     OR (LOWER(h2.hs_lifecyclestage) = 'marketing qualified lead'
         AND LOWER(s2.sf_lead_status) NOT IN ('mql','marketing qualified lead','new','open'))
) lm ON LOWER(TRIM(h.email)) = lm.email
LEFT JOIN (
    -- Duplicate email subquery
    SELECT LOWER(TRIM(email)) AS email
    FROM hubspot_contacts
    GROUP BY LOWER(TRIM(email))
    HAVING COUNT(*) > 1
) d ON LOWER(TRIM(h.email)) = d.email
LEFT JOIN clay_enrichment_mock c
    ON LOWER(TRIM(h.email)) = LOWER(TRIM(c.email));


-- ============================================================
-- 4. HIGH-INTENT LEADS NOT IN SALESFORCE
-- The hero query — quantifies revenue leakage directly
-- ============================================================

SELECT
    h.email,
    h.company,
    h.lead_score,
    h.industry,
    c.clay_voice_ai_fit,
    c.clay_hiring_cx,
    c.clay_outreach_angle,
    'High-intent lead not visible to Sales — revenue leakage' AS business_risk,
    'Create Salesforce lead, assign owner, alert Sales immediately' AS recommended_fix

FROM scored_leads h
LEFT JOIN salesforce_leads s
    ON LOWER(TRIM(h.email)) = LOWER(TRIM(s.email))
LEFT JOIN clay_enrichment_mock c
    ON LOWER(TRIM(h.email)) = LOWER(TRIM(c.email))

WHERE s.email IS NULL          -- no matching SF record
  AND h.lead_score >= 80       -- high-intent only

ORDER BY h.lead_score DESC;


-- ============================================================
-- 5. ROUTING RECOMMENDATION
-- ============================================================

SELECT
    h.email,
    h.company,
    h.lead_score,
    CASE
        WHEN h.lead_score >= 80 AND s.email IS NULL
            THEN 'RevOps Critical Fix before Sales Follow-Up'
        WHEN h.lead_score >= 80 AND (s.sf_owner IS NULL OR TRIM(s.sf_owner) = '')
            THEN 'Assign Owner Immediately'
        WHEN h.lead_score >= 80
            THEN 'AE Priority'
        WHEN h.lead_score BETWEEN 60 AND 79
            THEN 'SDR Priority'
        WHEN h.lead_score BETWEEN 40 AND 59
            THEN 'Nurture'
        ELSE 'Hold / Enrich Further'
    END AS routing_recommendation

FROM scored_leads h
LEFT JOIN salesforce_leads s
    ON LOWER(TRIM(h.email)) = LOWER(TRIM(s.email))

ORDER BY h.lead_score DESC;
