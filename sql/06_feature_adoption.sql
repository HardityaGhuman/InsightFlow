-- =====================================================================
-- 06 — Core feature adoption
-- =====================================================================
-- Business question:
--   Of the users who make it through onboarding, how many go on to use
--   the core feature — and do those users behave differently afterwards?
--
-- Output grain:
--   Two rows: activated users who reached the core feature in their
--   first 7 days, and activated users who did not.
--
-- Tableau:
--   Small two-bar comparison chart showing week-4 retention for each
--   group, with the group sizes in the tooltip.
--
-- Denominator:
--   ACTIVATED users only, not the whole eligible cohort. Asking whether
--   somebody adopted the core feature only makes sense once they have
--   finished onboarding, so activated users are the right population.
--   Each row's rates are then out of that row's own user count.
--
-- ---------------------------------------------------------------------
-- Why adoption is measured over 7 days here, not 28
-- ---------------------------------------------------------------------
--   Week-4 retention covers days 22-28. The project's general feature
--   adoption measure covers 28 days, which contains those same days. If
--   both were used here, a user could land in the "adopted" group
--   BECAUSE of activity on day 24 — the very activity that also marks
--   them retained in week 4. The gap between the groups would then be
--   partly a restatement of the definitions rather than a finding.
--
--   Measuring adoption over days 0-7 and retention over days 22-28
--   means the two measures share no days. The early-adoption question
--   is also the more useful one for a product team: it asks whether
--   getting to the core feature quickly goes with sticking around.
--
--   The 28-day adoption figure is still reported, as the core feature
--   adoption KPI in query 01. The two numbers answer different
--   questions and are not interchangeable.
--
-- ---------------------------------------------------------------------
-- IMPORTANT — this query does not show that the feature causes anything
-- ---------------------------------------------------------------------
--   The two groups here were not randomly assigned. Users chose whether
--   to reach the core feature, and the same underlying interest that
--   made somebody explore the product in week 1 is also a reason they
--   might come back in week 4. Separating the observation windows fixes
--   the overlap in the definitions; it does NOT fix this selection
--   effect. So a retention gap between the groups is an ASSOCIATION.
--
--   "Users who adopt the core feature retain better" is supported by
--   this output. "Getting users to the core feature will improve
--   retention" is not — that is a hypothesis, and testing it would need
--   an experiment that pushes a random half of users towards the
--   feature and compares the two halves.
--
--   This distinction is repeated in the README, the analyst brief, and
--   the AI system prompt, because it is the easiest mistake to make
--   with this kind of metric.
-- =====================================================================

WITH activated AS (
    -- The population for this question: eligible users who activated.
    SELECT *
    FROM user_funnel
    WHERE is_eligible
      AND is_activated
)

SELECT
    CASE WHEN adopted_core_feature_early
         THEN 'Reached core feature in first 7 days'
         ELSE 'Did not reach core feature in first 7 days'
    END AS adoption_group,

    count(*) AS users,

    -- Share of all activated users falling in this group. The first row
    -- is the early core feature adoption rate.
    round(count(*)::numeric / sum(count(*)) OVER (), 4) AS share_of_activated,

    -- Outcomes for each group, each out of that group's own size.
    count(*) FILTER (WHERE retained_week_4) AS retained_week_4_users,
    round(avg(retained_week_4::int), 4)     AS week_4_retention_rate,

    count(*) FILTER (WHERE converted)       AS converted_users,
    round(avg(converted::int), 4)           AS conversion_rate

FROM activated
GROUP BY adoption_group
ORDER BY adoption_group DESC;
