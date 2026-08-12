-- =====================================================================
-- 07 — Monthly trend
-- =====================================================================
-- Business question:
--   Is the product acquiring more users over time, and is it turning
--   them into activated, paying users as well as it used to?
--
-- Output grain:
--   One row per signup month.
--
-- Tableau:
--   Two stacked panes sharing one month axis: signups as bars in the
--   upper pane, activation_rate as a line in the lower one. Drag the
--   month label to Columns and both measures to Rows; Tableau makes two
--   panes automatically. Both values are already calculated here, so the
--   chart needs no calculated fields at all.
--
--   Deliberately NOT a dual axis. Signups (~1,400-1,950) and activation
--   rate (0.48-0.56) cannot share a scale, so a dual axis needs two
--   y-scales, and where the bars appear to cross the line is then set by
--   the chosen ranges rather than by the data.
--
-- Denominators — note that this query uses TWO different populations,
-- on purpose:
--   signups          — EVERY user who signed up that month. This is an
--                      acquisition volume count, so nobody is excluded.
--   activation_rate  — activated_users / eligible_users, where eligible
--   conversion_rate    means the user signed up at least 28 days before
--                      the data ends. February 2026 has signups but no
--                      eligible users, so its rates are NULL rather
--                      than a misleadingly low number. Tableau simply
--                      leaves a gap in the line.
--
-- Why the month-over-month change column is here:
--   The whole question is whether the rate is moving, and the reader
--   should not have to subtract two numbers in their head to see it.
--   LAG() gives the previous month's rate. This reports the size of the
--   change; it does not judge whether the change is good, bad, or worth
--   acting on.
-- =====================================================================

WITH monthly AS (
    SELECT
        signup_month,

        -- Acquisition volume: all signups, no eligibility filter
        count(*) AS signups,

        -- Rate population: only users with a full observation window
        count(*) FILTER (WHERE is_eligible) AS eligible_users,
        count(*) FILTER (WHERE is_eligible AND is_activated) AS activated_users,
        count(*) FILTER (WHERE is_eligible AND converted)    AS converted_users

    FROM user_funnel
    GROUP BY signup_month
),

rates AS (
    SELECT
        signup_month,
        to_char(signup_month, 'Mon YYYY') AS month_label,
        signups,
        eligible_users,
        activated_users,
        converted_users,
        -- NULLIF keeps February (0 eligible users) from dividing by zero
        round(activated_users::numeric / NULLIF(eligible_users, 0), 4) AS activation_rate,
        round(converted_users::numeric / NULLIF(eligible_users, 0), 4) AS conversion_rate
    FROM monthly
)

SELECT
    signup_month,
    month_label,
    signups,
    eligible_users,
    activated_users,
    activation_rate,
    converted_users,
    conversion_rate,
    -- Change versus the previous month, in percentage points
    round(
        (activation_rate - LAG(activation_rate) OVER (ORDER BY signup_month)) * 100,
        1
    ) AS activation_rate_change_pp
FROM rates
ORDER BY signup_month;
