-- =====================================================================
-- InsightFlow — schema definition
-- =====================================================================
-- Two tables only: users (one row per signed-up user) and events
-- (one row per product action). This is deliberately a simple
-- normalised model rather than a star schema: the dataset is small,
-- and the analytical value of the project is in the metric logic,
-- not in warehouse modelling.
--
-- Run with:  psql -d insightflow -f sql/00_schema.sql
-- =====================================================================

-- The user_funnel view is built on top of users, so it has to go first.
-- Without this, DROP TABLE users fails with a dependency error, and any
-- rebuild after the view exists would leave the old tables in place.
DROP VIEW IF EXISTS user_funnel;

DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS users;

-- ---------------------------------------------------------------------
-- users — the signup dimension table.
-- One row per user, capturing the attributes known at signup time.
-- CHECK constraints document the allowed segment values and stop bad
-- data entering the table during load.
-- ---------------------------------------------------------------------
CREATE TABLE users (
    user_id             INTEGER      PRIMARY KEY,
    signup_date         DATE         NOT NULL,
    country             TEXT         NOT NULL,
    plan                TEXT         NOT NULL
        CHECK (plan IN ('Free', 'Pro')),
    device              TEXT         NOT NULL
        CHECK (device IN ('Desktop', 'Mobile', 'Tablet')),
    company_size        TEXT         NOT NULL
        CHECK (company_size IN ('1-10', '11-50', '51-200', '201+')),
    acquisition_channel TEXT         NOT NULL
        CHECK (acquisition_channel IN
               ('Organic', 'Paid Search', 'Referral', 'Social', 'Email'))
);

-- ---------------------------------------------------------------------
-- events — the product activity fact table.
-- One row per action a user takes. event_timestamp is always on or
-- after the user's signup_date; this is enforced by the generator and
-- verified by sql/00_validate.sql.
-- ---------------------------------------------------------------------
CREATE TABLE events (
    event_id        INTEGER   PRIMARY KEY,
    user_id         INTEGER   NOT NULL REFERENCES users (user_id),
    event_timestamp TIMESTAMP NOT NULL,
    event_name      TEXT      NOT NULL
        CHECK (event_name IN (
            'signup',
            'onboarding_started',
            'onboarding_completed',
            'core_feature_used',
            'report_created',
            'invite_sent',
            'subscription_started',
            'subscription_cancelled'
        ))
);

-- ---------------------------------------------------------------------
-- Indexes.
-- Every analytical query in sql/ joins events back to users and filters
-- on either the event name or the timestamp, so those three columns are
-- indexed. The composite index on (user_id, event_name) serves the very
-- common "did this user ever do X" pattern used by the funnel and
-- activation queries.
-- ---------------------------------------------------------------------
CREATE INDEX idx_events_user_event ON events (user_id, event_name);
CREATE INDEX idx_events_name       ON events (event_name);
CREATE INDEX idx_events_timestamp  ON events (event_timestamp);
CREATE INDEX idx_users_signup_date ON users (signup_date);
