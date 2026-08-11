-- =====================================================================
-- InsightFlow — user_funnel view
-- =====================================================================
-- Business purpose:
--   Flatten the event stream into one row per user, recording whether
--   that user reached each funnel milestone. Every analytical query in
--   this project then becomes a simple aggregation over this view.
--
--   Defining the milestones once, here, means every metric in the
--   project shares the same definitions and the same denominator rule.
--   If a definition changes, it changes in exactly one place.
--
-- Run:  psql -d insightflow -f sql/00_user_funnel_view.sql
--
-- ---------------------------------------------------------------------
-- METRIC DEFINITIONS (the denominator rules are the important part)
-- ---------------------------------------------------------------------
--
-- data_end
--   The last day covered by the dataset (2026-02-28).
--
-- is_eligible  <-- THE DENOMINATOR FOR EVERY RATE IN THIS PROJECT
--   signup_date <= data_end - 28 days.
--   A user who signed up three days before the data ends has not had
--   the chance to activate, convert, or come back in week 4. Including
--   them would drag every rate down for reasons that have nothing to do
--   with the product. So all rate metrics use the eligible cohort as
--   their denominator, and that is stated on every query that uses it.
--
-- is_activated
--   Completed onboarding within 7 days of signup.
--   The 7-day bar is the product team's activation standard. Roughly
--   one in eight users who finish onboarding do so later than that, so
--   they count as onboarded but not activated.
--
-- Funnel stage flags (started_onboarding, completed_onboarding,
-- used_core_feature, converted)
--   Reached that stage within 28 days of signup. The funnel uses one
--   consistent 28-day observation window at every stage so the stages
--   are comparable with each other. Note this is deliberately looser
--   than the 7-day activation bar: completed_onboarding counts anyone
--   who finished within 28 days, is_activated only counts the first 7.
--
-- retained_week_4
--   Performed at least one qualifying event on days 22-28 after signup
--   (week 4, counting week N as days 7N-6 through 7N).
--   A qualifying event is any event except subscription_cancelled,
--   which is a churn signal rather than product usage.
-- =====================================================================

-- Dropped and recreated rather than CREATE OR REPLACE, because REPLACE
-- can only append columns to the end of a view. Adding a column in the
-- middle fails, and psql does not stop on that error by default, so the
-- old view would quietly survive and the exports would disagree with
-- the SQL files.
DROP VIEW IF EXISTS user_funnel;

CREATE VIEW user_funnel AS

WITH data_window AS (
    -- Derived from the data rather than hard-coded, so the view stays
    -- correct if the generator is re-run over a different date range.
    SELECT max(event_timestamp)::date AS data_end
    FROM events
),

milestones AS (
    -- One pass over the events table. FILTER gives the first timestamp
    -- for each milestone per user; a LEFT JOIN keeps users who never
    -- did anything beyond signing up.
    SELECT
        u.user_id,
        min(e.event_timestamp) FILTER (WHERE e.event_name = 'onboarding_started')
            AS onboarding_started_at,
        min(e.event_timestamp) FILTER (WHERE e.event_name = 'onboarding_completed')
            AS onboarding_completed_at,
        min(e.event_timestamp) FILTER (WHERE e.event_name = 'core_feature_used')
            AS first_core_feature_at,
        min(e.event_timestamp) FILTER (WHERE e.event_name = 'subscription_started')
            AS subscription_started_at,
        -- Week 4 = days 22-28 after signup. subscription_cancelled is
        -- excluded because cancelling is not product usage.
        count(*) FILTER (
            WHERE e.event_name <> 'subscription_cancelled'
              AND e.event_timestamp::date BETWEEN u.signup_date + 22
                                              AND u.signup_date + 28
        ) AS week_4_event_count
    FROM users u
    LEFT JOIN events e ON e.user_id = u.user_id
    GROUP BY u.user_id
)

SELECT
    u.user_id,
    u.signup_date,
    date_trunc('month', u.signup_date)::date AS signup_month,

    -- Segment attributes, all known at signup time
    u.country,
    u.plan,
    u.device,
    u.company_size,
    u.acquisition_channel,

    -- Denominator flag
    (u.signup_date <= w.data_end - 28) AS is_eligible,

    -- Funnel stages, each measured within 28 days of signup
    (m.onboarding_started_at IS NOT NULL
        AND m.onboarding_started_at::date <= u.signup_date + 28)
        AS started_onboarding,
    (m.onboarding_completed_at IS NOT NULL
        AND m.onboarding_completed_at::date <= u.signup_date + 28)
        AS completed_onboarding,
    (m.first_core_feature_at IS NOT NULL
        AND m.first_core_feature_at::date <= u.signup_date + 28)
        AS used_core_feature,
    (m.subscription_started_at IS NOT NULL
        AND m.subscription_started_at::date <= u.signup_date + 28)
        AS converted,

    -- Activation: the stricter 7-day bar
    (m.onboarding_completed_at IS NOT NULL
        AND m.onboarding_completed_at::date <= u.signup_date + 7)
        AS is_activated,

    -- Early core feature adoption: reached the core feature in the
    -- first 7 days. This exists so that adoption can be compared
    -- against week-4 retention without the two measures sharing any
    -- days. used_core_feature above spans 28 days, which overlaps
    -- week 4, so a user could be counted as an adopter because of the
    -- very activity that also marks them retained. Measuring adoption
    -- in days 0-7 and retention in days 22-28 removes that overlap.
    (m.first_core_feature_at IS NOT NULL
        AND m.first_core_feature_at::date <= u.signup_date + 7)
        AS adopted_core_feature_early,

    -- Retention
    (m.week_4_event_count > 0) AS retained_week_4

FROM users u
JOIN milestones m ON m.user_id = u.user_id
CROSS JOIN data_window w;
