-- =====================================================================
-- 08 — Channel and device combinations
-- =====================================================================
-- Business question:
--   Queries 04 and 05 look at one dimension at a time. Is there a
--   specific COMBINATION of acquisition channel and device that stands
--   out more than either dimension explains on its own — the best and
--   worst places a new user can enter the product?
--
-- Output grain:
--   One row per (acquisition channel, device) pair, 15 possible pairs,
--   filtered to those with enough users to be worth reading.
--
-- Tableau:
--   Ranked horizontal bar chart, or a highlight table with channel on
--   Rows and device on Columns coloured by activation_rate.
--
-- Denominator:
--   eligible_users within each combination.
--
-- Minimum sample size:
--   Combinations with fewer than 100 eligible users are excluded. With
--   a handful of users a rate swings wildly on one or two people, and a
--   ranked chart would put those noisy cells at the top and bottom. 100
--   is a judgement call, not a statistical test — it is a readability
--   guard, and the cut is stated here so it is not hidden.
--
-- gap_vs_overall_pp:
--   How far this combination sits from the overall activation rate, in
--   percentage points. It measures distance from average; it does not
--   say whether that distance is meaningful or what to do about it.
--
-- SQL note:
--   RANK() over the whole result set numbers the combinations from best
--   to worst activation, which is the ordering the chart needs.
-- =====================================================================

WITH eligible AS (
    SELECT * FROM user_funnel WHERE is_eligible
),

overall AS (
    SELECT avg(is_activated::int) AS overall_activation_rate
    FROM eligible
),

combos AS (
    SELECT
        acquisition_channel,
        device,
        count(*)                             AS eligible_users,
        count(*) FILTER (WHERE is_activated) AS activated_users,
        count(*) FILTER (WHERE converted)    AS converted_users
    FROM eligible
    GROUP BY acquisition_channel, device
    HAVING count(*) >= 100
)

SELECT
    c.acquisition_channel,
    c.device,
    c.acquisition_channel || ' / ' || c.device AS segment_combination,
    c.eligible_users,
    c.activated_users,
    round(c.activated_users::numeric / c.eligible_users, 4) AS activation_rate,
    round(c.converted_users::numeric / c.eligible_users, 4) AS conversion_rate,
    round(
        (c.activated_users::numeric / c.eligible_users - o.overall_activation_rate) * 100,
        1
    ) AS gap_vs_overall_pp,
    RANK() OVER (ORDER BY c.activated_users::numeric / c.eligible_users DESC)
        AS activation_rank
FROM combos c
CROSS JOIN overall o
ORDER BY activation_rate DESC;
