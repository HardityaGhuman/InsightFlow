"""
InsightFlow — synthetic data generator.

Creates two CSV files under data/raw/:

    users.csv   — one row per signed-up user
    events.csv  — one row per product action

The data is synthetic. It is generated so that the SQL analysis has
something real to find: several deliberate behavioural patterns are
planted in the probabilities below and documented in
docs/SYNTHETIC_PATTERNS.md. Nothing here should be presented as a
real-world finding.

The generator uses a fixed seed, so re-running it always produces the
same dataset. Standard library only — no pandas, no numpy.

Usage:
    python3 scripts/generate_data.py
"""

import csv
import os
import random
from datetime import date, datetime, timedelta

# =====================================================================
# Configuration
# =====================================================================

SEED = 42
N_USERS = 10_000

# Users sign up across a six-month window. Events can occur up to
# DATA_END, which is also the signup window's last day. Users who sign
# up near the end therefore have very little history — that censoring is
# intentional, and the SQL handles it with an "eligible cohort" rule
# (signup_date <= DATA_END - 28 days) so late signups do not drag the
# rates down.
SIGNUP_START = date(2025, 9, 1)
DATA_END = date(2026, 2, 28)

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

# ---------------------------------------------------------------------
# Segment distributions (weights, they do not need to sum to 1)
# ---------------------------------------------------------------------

COUNTRIES = {
    "United States": 30,
    "India": 18,
    "United Kingdom": 12,
    "Germany": 10,
    "Canada": 8,
    "Brazil": 8,
    "Australia": 7,
    "France": 7,
}

# plan is the tier the user picked at signup, not their current billing
# state. Keeping it a signup-time attribute means it can be used as a
# segment for conversion analysis without being circular.
PLANS = {"Free": 78, "Pro": 22}

DEVICES = {"Desktop": 55, "Mobile": 35, "Tablet": 10}

COMPANY_SIZES = {"1-10": 40, "11-50": 30, "51-200": 20, "201+": 10}

ACQUISITION_CHANNELS = {
    "Organic": 30,
    "Paid Search": 22,
    "Social": 20,
    "Referral": 15,
    "Email": 13,
}

# ---------------------------------------------------------------------
# Base funnel probabilities
#
# Each stage is conditional on the previous one:
#   signup -> onboarding_started -> onboarding_completed
#          -> core_feature_used  -> subscription_started
# ---------------------------------------------------------------------

P_ONBOARDING_STARTED = 0.86
P_ONBOARDING_COMPLETED = 0.74   # given onboarding_started
P_CORE_FEATURE_USED = 0.70      # given onboarding_completed
P_SUBSCRIPTION_STARTED = 0.20   # given core_feature_used
P_SUBSCRIPTION_CANCELLED = 0.12  # given subscription_started

# ---------------------------------------------------------------------
# Planted patterns — multiplicative modifiers on the base probabilities.
# A value of 1.00 means "this segment behaves like the baseline".
# These are kept moderate on purpose: the analysis should have to look
# for the differences rather than trip over them.
# ---------------------------------------------------------------------

# Onboarding completion (drives the activation metric)
COMPLETION_BY_DEVICE = {"Desktop": 1.06, "Tablet": 0.96, "Mobile": 0.83}
COMPLETION_BY_CHANNEL = {
    "Referral": 1.14,
    "Email": 1.05,
    "Organic": 1.00,
    "Paid Search": 0.95,
    "Social": 0.89,
}
COMPLETION_BY_PLAN = {"Free": 0.98, "Pro": 1.09}

# A dip in onboarding completion over the December-January period,
# standing in for a holiday-season slowdown or a bad release.
DIP_MONTHS = {(2025, 12), (2026, 1)}
COMPLETION_DIP = 0.90

# Paid conversion
CONVERSION_BY_CHANNEL = {
    "Referral": 1.35,
    "Email": 1.10,
    "Organic": 1.00,
    "Paid Search": 0.90,
    "Social": 0.55,   # high signup volume, weak conversion
}
CONVERSION_BY_PLAN = {"Free": 0.70, "Pro": 2.10}
CONVERSION_BY_COMPANY_SIZE = {
    "1-10": 0.85,
    "11-50": 1.00,
    "51-200": 1.25,
    "201+": 1.45,
}

# ---------------------------------------------------------------------
# Ongoing engagement, which drives the retention metric.
#
# Each week after signup a user is "active" with some probability. That
# probability starts at a base level and decays week over week.
# ---------------------------------------------------------------------

RETENTION_BASE = 0.55
RETENTION_WEEKLY_DECAY = 0.86
RETENTION_WEEKS = 26

# Users who never activated barely come back.
RETENTION_NOT_ACTIVATED = 0.25

# Additive bumps to the base weekly-active probability.
RETENTION_BONUS_PRO = 0.12
RETENTION_BONUS_CORE_FEATURE = 0.10   # association only, not causation
RETENTION_BONUS_BY_COMPANY_SIZE = {
    "1-10": 0.00,
    "11-50": 0.02,
    "51-200": 0.04,
    "201+": 0.05,
}
RETENTION_BONUS_REFERRAL = 0.04

# Events a returning user can fire in an active week, and how often.
ENGAGEMENT_EVENTS = {"core_feature_used": 60, "report_created": 28, "invite_sent": 12}


# =====================================================================
# Helpers
# =====================================================================


def weighted_choice(rng, weights):
    """Pick one key from a {value: weight} dict."""
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def clamp(p):
    """Keep a probability inside a sane range after modifiers are applied."""
    return max(0.02, min(0.98, p))


def business_hours_time(rng):
    """A time of day weighted towards working hours."""
    hour = rng.choices(
        range(24),
        weights=[1, 1, 1, 1, 1, 2, 4, 8, 14, 18, 20, 20,
                 18, 18, 20, 20, 18, 14, 10, 8, 6, 4, 3, 2],
        k=1,
    )[0]
    return timedelta(hours=hour, minutes=rng.randrange(60), seconds=rng.randrange(60))


def signup_day_weight(day):
    """
    Relative signup volume for a given calendar day.

    Two effects: steady growth across the window, and fewer signups at
    the weekend, which is normal for a B2B SaaS product.
    """
    growth = 1.0 + 0.5 * ((day - SIGNUP_START).days / (DATA_END - SIGNUP_START).days)
    weekend = 0.45 if day.weekday() >= 5 else 1.0
    return growth * weekend


# =====================================================================
# Users
# =====================================================================


def generate_users(rng):
    """Build the user list, spreading signups across the date window."""
    all_days = []
    day = SIGNUP_START
    while day <= DATA_END:
        all_days.append(day)
        day += timedelta(days=1)

    day_weights = [signup_day_weight(d) for d in all_days]
    signup_days = rng.choices(all_days, weights=day_weights, k=N_USERS)
    signup_days.sort()

    users = []
    for user_id, signup_date in enumerate(signup_days, start=1):
        users.append(
            {
                "user_id": user_id,
                "signup_date": signup_date,
                "country": weighted_choice(rng, COUNTRIES),
                "plan": weighted_choice(rng, PLANS),
                "device": weighted_choice(rng, DEVICES),
                "company_size": weighted_choice(rng, COMPANY_SIZES),
                "acquisition_channel": weighted_choice(rng, ACQUISITION_CHANNELS),
            }
        )
    return users


# =====================================================================
# Events
# =====================================================================


def generate_events_for_user(rng, user, next_event_id):
    """
    Walk one user through the funnel and their following weeks of
    activity, returning the events they generated.
    """
    events = []
    signup_date = user["signup_date"]
    signup_dt = datetime.combine(signup_date, datetime.min.time()) + business_hours_time(rng)

    def add(name, when):
        """Record an event, unless it would fall outside the data window."""
        nonlocal next_event_id
        if when.date() > DATA_END:
            return False
        events.append(
            {
                "event_id": next_event_id,
                "user_id": user["user_id"],
                "event_timestamp": when.strftime("%Y-%m-%d %H:%M:%S"),
                "event_name": name,
            }
        )
        next_event_id += 1
        return True

    add("signup", signup_dt)

    # --- Stage 1: onboarding started -------------------------------
    started = rng.random() < P_ONBOARDING_STARTED
    if not started:
        return events, next_event_id, False

    started_dt = signup_dt + timedelta(
        hours=rng.choices([0, 1, 24, 48], weights=[55, 20, 15, 10], k=1)[0],
        minutes=rng.randrange(120),
    )
    add("onboarding_started", started_dt)

    # --- Stage 2: onboarding completed (the activation event) ------
    p_complete = P_ONBOARDING_COMPLETED
    p_complete *= COMPLETION_BY_DEVICE[user["device"]]
    p_complete *= COMPLETION_BY_CHANNEL[user["acquisition_channel"]]
    p_complete *= COMPLETION_BY_PLAN[user["plan"]]
    if (signup_date.year, signup_date.month) in DIP_MONTHS:
        p_complete *= COMPLETION_DIP

    completed = rng.random() < clamp(p_complete)
    if not completed:
        return events, next_event_id, False

    # Most people finish onboarding quickly, but a tail finishes later.
    # Activation is defined as completing within 7 days, so this tail is
    # what makes that 7-day window a real decision rather than a
    # formality.
    days_to_complete = rng.choices(
        [0, 1, 2, 3, 5, 9, 14, 21],
        weights=[40, 22, 12, 8, 6, 5, 4, 3],
        k=1,
    )[0]
    completed_dt = started_dt + timedelta(days=days_to_complete, hours=rng.randrange(8))
    if not add("onboarding_completed", completed_dt):
        return events, next_event_id, False

    activated = days_to_complete + (started_dt.date() - signup_date).days <= 7

    # --- Stage 3: first use of the core feature --------------------
    used_core = rng.random() < P_CORE_FEATURE_USED
    core_dt = None
    if used_core:
        core_dt = completed_dt + timedelta(days=rng.randrange(0, 14), hours=rng.randrange(10))
        used_core = add("core_feature_used", core_dt)

    # --- Stage 4: paid conversion ----------------------------------
    subscribed = False
    if used_core:
        p_convert = P_SUBSCRIPTION_STARTED
        p_convert *= CONVERSION_BY_CHANNEL[user["acquisition_channel"]]
        p_convert *= CONVERSION_BY_PLAN[user["plan"]]
        p_convert *= CONVERSION_BY_COMPANY_SIZE[user["company_size"]]

        if rng.random() < clamp(p_convert):
            sub_dt = core_dt + timedelta(days=rng.randrange(1, 25), hours=rng.randrange(10))
            subscribed = add("subscription_started", sub_dt)

            # A minority churn out of their subscription later on.
            if subscribed and rng.random() < P_SUBSCRIPTION_CANCELLED:
                cancel_dt = sub_dt + timedelta(days=rng.randrange(30, 120))
                add("subscription_cancelled", cancel_dt)

    # --- Ongoing weekly engagement (drives retention) --------------
    base = RETENTION_BASE
    if not activated:
        base *= RETENTION_NOT_ACTIVATED
    if user["plan"] == "Pro":
        base += RETENTION_BONUS_PRO
    if used_core:
        base += RETENTION_BONUS_CORE_FEATURE
    if user["acquisition_channel"] == "Referral":
        base += RETENTION_BONUS_REFERRAL
    base += RETENTION_BONUS_BY_COMPANY_SIZE[user["company_size"]]

    for week in range(1, RETENTION_WEEKS + 1):
        p_active = clamp(base * (RETENTION_WEEKLY_DECAY ** week))
        if rng.random() >= p_active:
            continue
        for _ in range(rng.choices([1, 2, 3, 4], weights=[35, 33, 20, 12], k=1)[0]):
            when = (
                signup_dt
                + timedelta(days=7 * week + rng.randrange(7))
                + business_hours_time(rng)
            )
            add(weighted_choice(rng, ENGAGEMENT_EVENTS), when)

    return events, next_event_id, activated


# =====================================================================
# Entry point
# =====================================================================


def main():
    rng = random.Random(SEED)
    os.makedirs(OUT_DIR, exist_ok=True)

    users = generate_users(rng)

    all_events = []
    next_event_id = 1
    for user in users:
        user_events, next_event_id, _activated = generate_events_for_user(
            rng, user, next_event_id
        )
        all_events.extend(user_events)

    # Sort chronologically so the raw file reads like an event stream and
    # renumber so event_id increases with time.
    all_events.sort(key=lambda e: (e["event_timestamp"], e["user_id"]))
    for new_id, event in enumerate(all_events, start=1):
        event["event_id"] = new_id

    users_path = os.path.join(OUT_DIR, "users.csv")
    events_path = os.path.join(OUT_DIR, "events.csv")

    with open(users_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "user_id",
                "signup_date",
                "country",
                "plan",
                "device",
                "company_size",
                "acquisition_channel",
            ],
        )
        writer.writeheader()
        writer.writerows(users)

    with open(events_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["event_id", "user_id", "event_timestamp", "event_name"]
        )
        writer.writeheader()
        writer.writerows(all_events)

    print(f"users:  {len(users):>7,}  ->  {users_path}")
    print(f"events: {len(all_events):>7,}  ->  {events_path}")
    print(f"window: {SIGNUP_START} .. {DATA_END}  (seed={SEED})")


if __name__ == "__main__":
    main()
