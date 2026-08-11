-- =====================================================================
-- 04 — Activation by segment
-- =====================================================================
-- Business question:
--   Do some kinds of user get through onboarding far better than
--   others, and is any weak segment big enough to matter?
--
-- Output grain:
--   One row per (segment dimension, segment value). Long format, so
--   three dimensions sit in one table.
--
-- Tableau:
--   Bar chart. segment_value on Rows sorted by activation_rate,
--   activation_rate on Columns, segment_type as a filter so the reader
--   switches between channel, device and plan in a single worksheet.
--
-- Denominator:
--   eligible_users within each segment. activation_rate is
--   activated_users / eligible_users.
--
-- Why only these three dimensions:
--   Acquisition channel, device and signup plan are the ones that could
--   plausibly change whether somebody finishes onboarding — who they
--   are, what they are using, and how committed they were at signup.
--   Country and company size are held back for the conversion question,
--   where they are more relevant, rather than producing every possible
--   breakdown.
--
-- share_of_signups is included because a low activation rate only
-- matters if the segment is large. It is context for the rate, not a
-- separate metric.
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
           count(*)                          AS eligible_users,
           count(*) FILTER (WHERE is_activated) AS activated_users
    FROM eligible
    GROUP BY 2

    UNION ALL
    SELECT 'Device', device,
           count(*),
           count(*) FILTER (WHERE is_activated)
    FROM eligible
    GROUP BY 2

    UNION ALL
    SELECT 'Signup plan', plan,
           count(*),
           count(*) FILTER (WHERE is_activated)
    FROM eligible
    GROUP BY 2
)

SELECT
    s.segment_type,
    s.segment_value,
    s.eligible_users,
    s.activated_users,
    round(s.activated_users::numeric / s.eligible_users, 4) AS activation_rate,
    round(s.eligible_users::numeric / t.all_eligible_users, 4) AS share_of_signups
FROM by_segment s
CROSS JOIN total t
ORDER BY s.segment_type, activation_rate DESC;
