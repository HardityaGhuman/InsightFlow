-- =====================================================================
-- 01 — Headline KPIs
-- =====================================================================
-- Business question:
--   How are new users doing overall — do they activate, do they pay,
--   and are they still around a month later?
--
-- Output grain:
--   One row per KPI (long format), 4 rows total.
--
-- Tableau:
--   The KPI card band at the top of the dashboard. Long format means
--   one worksheet can render all four tiles side by side rather than
--   needing a separate data source per tile.
--
-- Denominator:
--   Every rate here is over the ELIGIBLE COHORT — users who signed up
--   at least 28 days before the data ends, so they had a full chance to
--   reach each milestone. Feature adoption is the one exception and
--   states its own denominator in the row.
-- =====================================================================

WITH eligible AS (
    SELECT * FROM user_funnel WHERE is_eligible
)

SELECT 'Activation rate'  AS metric_name,
       1 AS display_order,
       round(avg(is_activated::int), 4)     AS metric_value,
       count(*)                             AS denominator,
       'Eligible users'                     AS denominator_label,
       'Completed onboarding within 7 days of signup' AS definition
FROM eligible

UNION ALL
SELECT 'Conversion rate', 2,
       round(avg(converted::int), 4),
       count(*),
       'Eligible users',
       'Started a subscription within 28 days of signup'
FROM eligible

UNION ALL
SELECT 'Week-4 retention', 3,
       round(avg(retained_week_4::int), 4),
       count(*),
       'Eligible users',
       'Active on days 22-28 after signup'
FROM eligible

UNION ALL
-- Feature adoption has a different, narrower denominator: it only makes
-- sense to ask whether ACTIVATED users go on to use the core feature.
SELECT 'Core feature adoption', 4,
       round(avg(used_core_feature::int), 4),
       count(*),
       'Activated users',
       'Activated users who used the core feature within 28 days'
FROM eligible
WHERE is_activated

ORDER BY display_order;
