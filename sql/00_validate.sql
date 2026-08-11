-- =====================================================================
-- InsightFlow — data quality checks
-- =====================================================================
-- Run after loading:  psql -d insightflow -f sql/00_validate.sql
--
-- Each check returns a row with the number of problems found. Every
-- "problems" value should be 0. The reference checks at the bottom are
-- informational rather than pass/fail.
-- =====================================================================

\echo '--- Integrity checks (problems should all be 0) ---'

SELECT 'duplicate user_id' AS check_name,
       count(*) - count(DISTINCT user_id) AS problems
FROM users

UNION ALL
SELECT 'duplicate event_id',
       count(*) - count(DISTINCT event_id)
FROM events

UNION ALL
SELECT 'null in required user column',
       count(*)
FROM users
WHERE user_id IS NULL OR signup_date IS NULL OR country IS NULL
   OR plan IS NULL OR device IS NULL OR company_size IS NULL
   OR acquisition_channel IS NULL

UNION ALL
SELECT 'null in required event column',
       count(*)
FROM events
WHERE event_id IS NULL OR user_id IS NULL
   OR event_timestamp IS NULL OR event_name IS NULL

UNION ALL
-- The foreign key makes this impossible, but the check documents the
-- expectation for anyone reading the analysis.
SELECT 'event referencing missing user',
       count(*)
FROM events e
LEFT JOIN users u ON u.user_id = e.user_id
WHERE u.user_id IS NULL

UNION ALL
SELECT 'event dated before its user signed up',
       count(*)
FROM events e
JOIN users u ON u.user_id = e.user_id
WHERE e.event_timestamp::date < u.signup_date

UNION ALL
SELECT 'timestamp outside the data window',
       count(*)
FROM events
WHERE event_timestamp::date < DATE '2025-09-01'
   OR event_timestamp::date > DATE '2026-02-28'

UNION ALL
SELECT 'user without a signup event',
       count(*)
FROM users u
WHERE NOT EXISTS (
    SELECT 1 FROM events e
    WHERE e.user_id = u.user_id AND e.event_name = 'signup'
)

UNION ALL
-- Funnel ordering: nobody should complete onboarding before starting it.
SELECT 'onboarding completed before started',
       count(*)
FROM (
    SELECT user_id,
           min(event_timestamp) FILTER (WHERE event_name = 'onboarding_started')  AS started_at,
           min(event_timestamp) FILTER (WHERE event_name = 'onboarding_completed') AS completed_at
    FROM events
    GROUP BY user_id
) t
WHERE completed_at IS NOT NULL
  AND (started_at IS NULL OR completed_at < started_at);

\echo ''
\echo '--- Volume and coverage (informational) ---'

SELECT
    (SELECT count(*) FROM users)                            AS total_users,
    (SELECT count(*) FROM events)                           AS total_events,
    (SELECT round(count(*)::numeric / 10000, 1) FROM events) AS events_per_user,
    (SELECT count(*) FROM users u
      WHERE NOT EXISTS (SELECT 1 FROM events e
                        WHERE e.user_id = u.user_id
                          AND e.event_name <> 'signup'))    AS users_with_signup_only,
    (SELECT min(signup_date) FROM users)                    AS first_signup,
    (SELECT max(signup_date) FROM users)                    AS last_signup,
    (SELECT max(event_timestamp)::date FROM events)         AS last_event;

\echo ''
\echo '--- Event mix ---'

SELECT event_name,
       count(*) AS events,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct_of_events
FROM events
GROUP BY event_name
ORDER BY events DESC;

\echo ''
\echo '--- Segment distribution (should be broadly balanced, no empty cells) ---'

SELECT 'acquisition_channel' AS segment, acquisition_channel AS value,
       count(*) AS users, round(100.0 * count(*) / 10000, 1) AS pct
FROM users GROUP BY 2
UNION ALL
SELECT 'device', device, count(*), round(100.0 * count(*) / 10000, 1)
FROM users GROUP BY 2
UNION ALL
SELECT 'plan', plan, count(*), round(100.0 * count(*) / 10000, 1)
FROM users GROUP BY 2
UNION ALL
SELECT 'company_size', company_size, count(*), round(100.0 * count(*) / 10000, 1)
FROM users GROUP BY 2
ORDER BY 1, 3 DESC;
