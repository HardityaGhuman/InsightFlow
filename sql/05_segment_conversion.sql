-- =====================================================================
-- 05 — Conversion by segment
-- =====================================================================
-- Business question:
--   Which segments actually turn into paying customers, and is the
--   product acquiring users from places that do not pay?
--
-- Output grain:
--   One row per (segment dimension, segment value). Long format.
--
-- Tableau:
--   Bar chart, same shape as query 04 so the two read as a pair.
--   segment_value on Rows sorted by conversion_rate, segment_type as a
--   filter.
--
-- Denominator:
--   eligible_users within each segment. conversion_rate is
--   converted_users / eligible_users, where a converted user started a
--   subscription within 28 days of signing up.
--
-- Why these three dimensions:
--   Acquisition channel says where the user came from, signup plan says
--   how committed they were on day one, and company size is the closest
--   thing this dataset has to a proxy for budget. Device is left out
--   here: it is an onboarding-experience question, not a
--   willingness-to-pay one, so it belongs in query 04.
--
-- Reading share_of_signups next to conversion_rate is the point of this
-- query. A channel that supplies a large share of signups but converts
-- below average is a different kind of problem from a small weak
-- channel. This query reports both numbers; it does not decide which
-- case applies.
-- =====================================================================

WITH eligible AS (
    SELECT * FROM user_funnel WHERE is_eligible
),

total AS (
    SELECT count(*) AS all_eligible_users FROM eligible
),

by_segment AS (
    SELECT 'Acquisition channel' AS segment_type,
           acquisition_channel   AS segment_value,
           count(*)                        AS eligible_users,
           count(*) FILTER (WHERE converted) AS converted_users
    FROM eligible
    GROUP BY 2

    UNION ALL
    SELECT 'Signup plan', plan,
           count(*),
           count(*) FILTER (WHERE converted)
    FROM eligible
    GROUP BY 2

    UNION ALL
    SELECT 'Company size', company_size,
           count(*),
           count(*) FILTER (WHERE converted)
    FROM eligible
    GROUP BY 2
)

SELECT
    s.segment_type,
    s.segment_value,
    s.eligible_users,
    s.converted_users,
    round(s.converted_users::numeric / s.eligible_users, 4)    AS conversion_rate,
    round(s.eligible_users::numeric / t.all_eligible_users, 4) AS share_of_signups
FROM by_segment s
CROSS JOIN total t
ORDER BY s.segment_type, conversion_rate DESC;
