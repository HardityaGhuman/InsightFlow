-- =====================================================================
-- 03 — Cohort retention
-- =====================================================================
-- Business question:
--   Once users sign up, do they keep coming back — and are more recent
--   signup cohorts holding up as well as earlier ones?
--
-- Output grain:
--   One row per (signup cohort month, week number), weeks 1-8.
--
-- Tableau:
--   Heatmap. cohort_label on Rows, week_number on Columns,
--   retention_rate on Colour, and the rate again as Label.
--
-- Denominator:
--   cohort_users — every user who signed up in that month. The rate is
--   retained_users / cohort_users.
--
-- Handling incomplete data:
--   A cohort week is only shown once EVERY user in that cohort has had
--   time to reach it. The January cohort therefore stops at week 4, and
--   February drops out entirely, because the data ends on 2026-02-28.
--   This is what produces the triangular shape a retention heatmap is
--   supposed to have. The alternative — showing partial weeks — would
--   invent a retention collapse that is really just missing time.
--
-- Week numbering:
--   Week N covers days 7N-6 through 7N after signup. Week 1 is days
--   1-7, week 4 is days 22-28. A user counts as retained in a week if
--   they did anything except cancel a subscription during it.
-- =====================================================================

WITH data_window AS (
    SELECT max(event_timestamp)::date AS data_end
    FROM events
),

weeks AS (
    SELECT generate_series(1, 8) AS week_number
),

cohorts AS (
    -- Cohort size and the latest signup in the cohort. The latest
    -- signup is what decides whether the whole cohort has had time to
    -- reach a given week.
    SELECT
        date_trunc('month', signup_date)::date AS cohort_month,
        count(*)          AS cohort_users,
        max(signup_date)  AS last_signup_in_cohort
    FROM users
    GROUP BY 1
),

cells AS (
    -- One row per cohort/week that is fully observable in the dataset.
    SELECT c.cohort_month, c.cohort_users, w.week_number
    FROM cohorts c
    CROSS JOIN weeks w
    CROSS JOIN data_window d
    WHERE c.last_signup_in_cohort + (7 * w.week_number) <= d.data_end
),

retained AS (
    -- Count, for each cohort/week cell, how many users were active.
    SELECT
        cl.cohort_month,
        cl.week_number,
        count(DISTINCT e.user_id) AS retained_users
    FROM cells cl
    JOIN users u
      ON date_trunc('month', u.signup_date)::date = cl.cohort_month
    JOIN events e
      ON e.user_id = u.user_id
     AND e.event_name <> 'subscription_cancelled'
     AND e.event_timestamp::date BETWEEN u.signup_date + (7 * cl.week_number - 6)
                                     AND u.signup_date + (7 * cl.week_number)
    GROUP BY 1, 2
)

SELECT
    cl.cohort_month,
    to_char(cl.cohort_month, 'Mon YYYY')      AS cohort_label,
    cl.week_number,
    cl.cohort_users,
    COALESCE(r.retained_users, 0)             AS retained_users,
    round(COALESCE(r.retained_users, 0)::numeric / cl.cohort_users, 4)
                                              AS retention_rate
FROM cells cl
LEFT JOIN retained r
       ON r.cohort_month = cl.cohort_month
      AND r.week_number  = cl.week_number
ORDER BY cl.cohort_month, cl.week_number;
