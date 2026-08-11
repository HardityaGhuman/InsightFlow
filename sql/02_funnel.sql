-- =====================================================================
-- 02 — Activation funnel
-- =====================================================================
-- Business question:
--   Between signing up and paying, which milestones do users fail to
--   reach, and which single step loses the most people?
--
-- Output grain:
--   One row per funnel stage, 5 rows, ordered from top to bottom.
--
-- Tableau:
--   Horizontal bar chart, stages on Rows sorted by stage_order, users
--   on Columns. The two percentage columns go in the tooltip.
--
-- Denominator:
--   pct_of_signups         — share of the eligible cohort
--   pct_of_previous_stage  — share of the stage immediately above,
--                            which is what tells you where the biggest
--                            single leak is
--
-- ---------------------------------------------------------------------
-- What kind of funnel this is
-- ---------------------------------------------------------------------
--   This is a MILESTONE-REACH funnel, not a strictly ordered sequence.
--   Each stage counts users who reached that milestone within 28 days
--   of signing up. Nothing in the SQL requires stage N to have happened
--   after stage N-1.
--
--   That distinction was measured rather than assumed. In this dataset
--   there are zero cases of completing onboarding without starting it,
--   subscribing before using the core feature, or subscribing without
--   using the core feature. There is one real violation: 1.30% of the
--   eligible cohort used the core feature before finishing onboarding,
--   because ongoing usage begins in week 1 while a minority finish
--   onboarding as late as day 23.
--
--   Enforcing strict ordering would move this stage from 4,355 users to
--   4,311 — 44 users, 0.53%, and the funnel would read 52.4% instead of
--   52.9%. The looser definition was kept because it is simpler to state
--   and to defend, and because the difference is immaterial. The
--   measured violation rate is recorded here so the choice is visible
--   rather than hidden.
--
-- SQL note:
--   LAG() is used to reach the previous stage's user count. Comparing
--   a row to the row above it is exactly what window functions are for,
--   so this is a case where one genuinely helps rather than decorating
--   the query.
-- =====================================================================

WITH eligible AS (
    SELECT * FROM user_funnel WHERE is_eligible
),

stages AS (
    -- One row per stage. Each stage counts users who reached it within
    -- 28 days of signing up, so the stages are directly comparable.
    SELECT 1 AS stage_order, 'Signed up'            AS stage_name, count(*) AS users FROM eligible
    UNION ALL
    SELECT 2, 'Started onboarding',   count(*) FILTER (WHERE started_onboarding)   FROM eligible
    UNION ALL
    SELECT 3, 'Completed onboarding', count(*) FILTER (WHERE completed_onboarding) FROM eligible
    UNION ALL
    SELECT 4, 'Used core feature',    count(*) FILTER (WHERE used_core_feature)    FROM eligible
    UNION ALL
    SELECT 5, 'Started subscription', count(*) FILTER (WHERE converted)            FROM eligible
)

SELECT
    stage_order,
    stage_name,
    users,
    -- Share of everyone who signed up
    round(users::numeric / max(users) OVER (), 4) AS pct_of_signups,
    -- Share of the stage directly above; NULL for the first stage
    round(users::numeric / LAG(users) OVER (ORDER BY stage_order), 4)
        AS pct_of_previous_stage,
    -- How many people were lost at this step
    LAG(users) OVER (ORDER BY stage_order) - users AS users_lost_at_step
FROM stages
ORDER BY stage_order;
