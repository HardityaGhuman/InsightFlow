#!/usr/bin/env python3
"""Turn the metrics already calculated by SQL into a stakeholder brief.

The point of this script is the separation it enforces:

    PostgreSQL -> SQL -> data/tableau/*.csv -> metrics JSON -> LLM -> prose

PostgreSQL is the source of truth. Every number in the brief was
calculated deterministically by SQL before the model was called. The
model never queries the database, never sees a raw event, and does no
arithmetic whatsoever - every gap, growth rate and rounded percentage is
computed here in Python first. Its only job is to choose what matters
and say it in English.

Two outputs are written to outputs/:

    metrics.json        the exact input the model was given
    analyst_brief.md    the brief it wrote

Saving the input beside the output lets any claim be traced back to its
number. verify_numbers() then re-reads the brief and fails if a figure in
it was not in the input - a check on grounding, not on coherence.

Usage:
    python3 scripts/generate_ai_brief.py            # calls the LLM
    python3 scripts/generate_ai_brief.py --dry-run  # metrics.json only
    python3 scripts/generate_ai_brief.py --model groq/openai/gpt-oss-120b

Requires an API key for whichever provider is called - GEMINI_API_KEY by
default, GROQ_API_KEY for groq/... models - in the environment or in a
.env file in the project root (gitignored). See PROVIDER_KEYS. The key
is never written, logged or echoed by this script.

Exit codes: 2 missing key, 3 the LLM call failed, 4 a figure in the
brief was not in the input, 5 the request would exceed the provider's
token budget.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLEAU_DIR = ROOT / "data" / "tableau"
OUTPUT_DIR = ROOT / "outputs"

# Chosen by running it against gpt-oss-120b on the same prompt and
# payload; both stayed grounded, this one surfaced more of the signal.
# Override with --model or INSIGHTFLOW_MODEL.
DEFAULT_MODEL = "gemini/gemini-3.5-flash"

# Environment variable each provider prefix needs, so the script can say
# which key is missing rather than letting litellm fail deeper down.
PROVIDER_KEYS = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

TEMPERATURE = 0.2

# Token limits vary by provider, so they live here rather than as global
# constants. max_tokens must cover a reasoning model's thinking tokens as
# well as the brief itself, or the brief gets truncated. token_budget is
# the most one call may consume, input and output together, before this
# script refuses to send - Groq's free tier meters tokens per minute.
PROVIDER_LIMITS = {
    "groq": {"max_tokens": 1000, "token_budget": 8000},
    "gemini": {"max_tokens": 8000, "token_budget": 250000},
}
DEFAULT_LIMITS = {"max_tokens": 1500, "token_budget": 8000}

# Columns sent to the model. Anything omitted is derivable, duplicated,
# or an identifier the brief has no reason to quote.
PAYLOAD_COLUMNS = {
    "kpis": (
        "metric_name", "metric_value", "denominator", "denominator_label",
    ),
    "funnel": (
        "stage_name", "users", "pct_of_signups", "pct_of_previous_stage",
        "users_lost_at_step",
    ),
    "monthly_trends": (
        "month_label", "signups", "eligible_users", "activation_rate",
        "conversion_rate", "activation_rate_change_pp",
    ),
    "retention": (
        "cohort_label", "week_number", "cohort_users", "retention_rate",
    ),
    "segments": (
        "segment_type", "segment_value", "eligible_users",
        "share_of_signups", "activation_rate", "conversion_rate",
    ),
    "feature_adoption": (
        "adoption_group", "users", "share_of_activated",
        "week_4_retention_rate", "conversion_rate",
    ),
    "combos": (
        "segment_combination", "eligible_users", "activation_rate",
        "conversion_rate", "gap_vs_overall_pp",
    ),
}

# Metric definitions, restated for the model so it does not have to
# infer them from column names. These match sql/00_user_funnel_view.sql.
DEFINITIONS = {
    "eligible_cohort": (
        "Signed up on or before 2026-01-31, at least 28 days before the "
        "data ends. Denominator for every rate except feature adoption."
    ),
    "activation": "Completed onboarding within 7 days of signup.",
    "conversion": "Started a subscription within 28 days of signup.",
    "week_4_retention": "Active on days 22-28 after signup.",
    "feature_adoption_early": (
        "Reached the core feature within the first 7 days. The 7-day "
        "window shares no days with week-4 retention (days 22-28); an "
        "earlier 28-day version overlapped it and inflated the association."
    ),
    "funnel": (
        "Each stage counts users reaching that milestone within 28 days. "
        "Milestone-reach, not a strict sequence: 1.30% reached the core "
        "feature before completing onboarding."
    ),
}

# PCTF - Persona, Context, Task, Format: who is speaking, what they
# know, what they must do, what the output looks like.
SYSTEM_PROMPT = """# PERSONA

You are a product analyst writing for the product manager of a
business-to-business SaaS product. You are trusted because you are
careful: you say what the evidence supports, you name what it does not,
and you never dress a hypothesis up as a finding. You write in plain
prose for a busy reader who will act on what you say.

# CONTEXT

The metrics in the user message were calculated deterministically in
SQL and handed to you as JSON. You have no database access and cannot
see a single raw event. Read `definitions` before interpreting any
number: each metric's time window matters.

Every comparison is pre-computed in `derived_comparisons` - gaps, growth
rates, step-to-step funnel losses. Rates arrive as percentages already
rounded to one decimal place; see `units`. You are not required to do
arithmetic of any kind, including converting or re-rounding a rate, and
you must not. Copy the numbers as given.

The channel-by-device leaderboard is sent as its top 3 and bottom 3 of
15 cells. The middle is withheld; do not speculate about it.

The dataset is synthetic, generated with a fixed seed for a portfolio
project. It is not real customer behaviour and carries no real business
impact.

# TASK

Identify what matters in this data and brief the product manager on it.
Lead with the single most consequential thing, support it with the
figures that establish it, name the strongest segment signal, and say
what should be looked at next.

Prioritise movement and difference over restatement. A headline rate
repeated back is not a finding; a rate that is changing, or a segment
that departs from the average, is.

## Rules

1. Use only the supplied metrics. Every figure you write must appear in
   the input exactly as given.
2. Never calculate. If a difference, gap, ratio or growth rate is not in
   the input, do not state it - not even a subtraction you are confident
   about.
3. Never claim causation, and never imply it. Every relationship here
   is an association between two things measured on the same users.

   Do not write that one thing is "driven by", "caused by", "due to",
   "because of", "the reason for", "explains" or "leads to" another. Do
   not call anything "the most promising path", "the key to", "critical"
   or "the biggest opportunity", and do not say that changing one number
   would improve another.

   Write instead: "the largest observed in-product drop", "X is
   associated with Y", "this may indicate onboarding friction", "worth
   investigating". Where you want to explain a pattern, mark it as a
   hypothesis in those words.

   Adopt a cold analyst register throughout. Describe what was measured
   and what it is consistent with. Enthusiasm reads as advocacy, and
   advocacy is how an association turns into a causal claim.
4. Separate findings from hypotheses, in those words where it helps. A
   finding is in the data; a hypothesis is your explanation for it.
5. Frame recommendations as investigations or prioritisation
   suggestions, never as guaranteed fixes or as projected uplift.
6. Never present the data as real. Do not write about revenue impact,
   customer sentiment, competitors, or anything outside the input.
7. If the evidence will not support a claim you want to make, say so
   plainly and move on.

## Edge cases

Specific ways this dataset is misread. Each is a mistake a careless
analyst would make.

- **Null means not yet measurable, not zero.** The most recent signup
  month has signups but no eligible users: its 28-day window has not
  closed, so its rates are null. Never report it as a collapse to 0%,
  never put it in a trend, never call it the worst month. Same for the
  first month's month-over-month change, null for want of a prior month.
- **Denominators differ.** Activation, conversion and week-4 retention
  are shares of the eligible cohort; core feature adoption is a share of
  activated users, a smaller group. Check the denominator label before
  comparing two rates.
- **The paywall is not a product defect.** The largest raw funnel drop
  is the final step to a paid subscription - a pricing boundary most
  users of any freemium product never cross. Do not call it the biggest
  problem without saying it is a paywall. For where the product loses
  people, use the pre-computed largest in-product drop, which excludes
  it.
- **The funnel is milestone-reach, not a strict sequence.** A small
  fraction reached a later milestone before an earlier one. Do not
  describe it as an ordered journey.
- **Feature adoption uses a 7-day window on purpose.** An earlier 28-day
  version overlapped week-4 retention and inflated the association. If
  you cite the retention gap, note it is small next to the conversion
  gap.
- **Small cells are noisy.** Some channel-by-device cells rest on about
  a hundred users. Check the cell's user count before leaning on it, and
  say when a difference rests on a small group.
- **Segments are alternative cuts, not parts.** Channel, device, plan
  and company size each partition the whole cohort separately. Never add
  rates or counts across segment types, and never treat two cuts as
  independent evidence for one claim.
- **Rate and volume can disagree.** A segment can grow in absolute terms
  while its rate falls; a channel can be large and weak at once. Say
  which you mean.
- **Missing evidence is not weak evidence.** Where the input cannot
  distinguish two explanations, say so rather than picking the more
  interesting one.

# FORMAT

Markdown. No preamble, no restating this instruction, no closing
pleasantries, no bullet-point summary at the end.

You are writing for a product manager, not documenting a data
structure. Three consequences:

- **Never name a field, key or JSON path.** Do not write
  `derived_comparisons.largest_in_product_funnel_drop`,
  `activation_rate = 0.6653`, or "pct of previous stage = 0.6815". The
  reader has not seen the input and never will. Cite the figure, not
  where it lives.
- **Write numbers as a person would.** Rates as percentages, not
  decimals: 66.5%, not 0.6653. Counts with separators: 2,255 users.
  Differences in percentage points: "26.1 percentage points" or
  "26.1pp". Plain ASCII punctuation, and no space before a percent sign.
- **Do not promise outcomes.** "Improving onboarding completion would
  move more users toward activation" is a projection, and you have no
  evidence for it. Write what the data shows and what is worth
  examining, and leave the size of any improvement unstated.

Exactly these five level-2 headings, in this order, each followed by
prose:

## Executive finding
## Supporting evidence
## Most important segment signal
## Recommended next investigation
## Limitation

Guidance per section:

- **Executive finding** - one paragraph. The single most consequential
  observation in the data, stated as what was measured. Not a
  recommendation, not a diagnosis, and not a claim about what would
  happen if something changed.
- **Supporting evidence** - the figures that establish it, quoted from
  the input. Short paragraphs or a small list are both fine.
- **Most important segment signal** - the segment difference that most
  deserves attention, with its size and the group it rests on.
- **Recommended next investigation** - what to look at next and what
  answer would change the decision. Investigations, not fixes.
- **Limitation** - what this analysis cannot establish. Include that the
  data is synthetic and that the relationships are associations rather
  than causes.

Under 600 words in total."""


# --------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------

def load_env(path: Path) -> None:
    """Read KEY=VALUE lines from .env without adding a dependency.

    Existing environment variables win, so an exported key overrides the
    file. Values are never logged.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _cell(value: str):
    """Convert a CSV cell to int, float, None, or leave it as text."""
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def read_csv(name: str) -> list[dict]:
    path = TABLEAU_DIR / name
    if not path.exists():
        sys.exit(
            f"Missing {path}. Run ./scripts/export_metrics.sh first."
        )
    with path.open(newline="") as handle:
        return [
            {key: _cell(value) for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def pick(rows: list[dict], **match) -> dict:
    """Return the single row matching every key=value pair given."""
    hits = [r for r in rows if all(r[k] == v for k, v in match.items())]
    if len(hits) != 1:
        sys.exit(f"Expected exactly 1 row for {match}, found {len(hits)}.")
    return hits[0]


# --------------------------------------------------------------------
# Derived comparisons
# --------------------------------------------------------------------

def pp(a: float, b: float) -> float:
    """Percentage-point difference between two rates, to 1dp."""
    return round((a - b) * 100, 1)


def build_derived(data: dict) -> dict:
    """Compute every comparison the brief might need.

    Exists so the model never performs arithmetic: each value is a
    subtraction or ratio over numbers SQL already produced.
    """
    months = [r for r in data["monthly_trends"] if r["eligible_users"]]
    first, last = months[0], months[-1]

    funnel = data["funnel"]
    # Largest step-to-step loss, ignoring the paywall step, which is a
    # pricing boundary rather than a product defect.
    in_product = [r for r in funnel if r["stage_order"] in (2, 3, 4)]
    worst = min(in_product, key=lambda r: r["pct_of_previous_stage"])

    activation = data["segment_activation"]
    combos = data["top_segments"]
    early = pick(
        data["feature_adoption"],
        adoption_group="Reached core feature in first 7 days",
    )
    late = pick(
        data["feature_adoption"],
        adoption_group="Did not reach core feature in first 7 days",
    )

    def spread(rows, key, segment_type=None):
        subset = [
            r for r in rows
            if segment_type is None or r["segment_type"] == segment_type
        ]
        best = max(subset, key=lambda r: r[key])
        worst_row = min(subset, key=lambda r: r[key])
        return best, worst_row

    dev_best, dev_worst = spread(activation, "activation_rate", "Device")
    chan_best, chan_worst = spread(
        activation, "activation_rate", "Acquisition channel"
    )
    combo_best = max(combos, key=lambda r: r["activation_rate"])
    combo_worst = min(combos, key=lambda r: r["activation_rate"])

    return {
        "signup_growth_first_to_last_eligible_month_pct": round(
            (last["signups"] / first["signups"] - 1) * 100, 1
        ),
        "signup_growth_months": f"{first['month_label']} to {last['month_label']}",
        "activation_change_first_to_last_eligible_month_pp": pp(
            last["activation_rate"], first["activation_rate"]
        ),
        "largest_single_month_activation_drop_pp": min(
            r["activation_rate_change_pp"] for r in months
            if r["activation_rate_change_pp"] is not None
        ),
        "largest_in_product_funnel_drop": {
            "stage": worst["stage_name"],
            "pct_of_previous_stage": worst["pct_of_previous_stage"],
            "users_lost": worst["users_lost_at_step"],
            "next_stage_pass_rate": pick(
                funnel, stage_order=worst["stage_order"] + 1
            )["pct_of_previous_stage"],
        },
        "device_activation_gap_pp": pp(
            dev_best["activation_rate"], dev_worst["activation_rate"]
        ),
        "device_gap_between": [
            dev_best["segment_value"], dev_worst["segment_value"]
        ],
        "channel_activation_gap_pp": pp(
            chan_best["activation_rate"], chan_worst["activation_rate"]
        ),
        "channel_gap_between": [
            chan_best["segment_value"], chan_worst["segment_value"]
        ],
        "channel_device_activation_spread_pp": pp(
            combo_best["activation_rate"], combo_worst["activation_rate"]
        ),
        "channel_device_spread_between": [
            combo_best["segment_combination"],
            combo_worst["segment_combination"],
        ],
        "early_adoption_conversion_gap_pp": pp(
            early["conversion_rate"], late["conversion_rate"]
        ),
        "early_adoption_week_4_retention_gap_pp": pp(
            early["week_4_retention_rate"], late["week_4_retention_rate"]
        ),
    }


# Fields the SQL exports as a 0-1 proportion. They are converted to
# percentages, rounded once, before the model sees them.
RATE_KEYS = frozenset({
    "metric_value", "pct_of_signups", "pct_of_previous_stage",
    "activation_rate", "conversion_rate", "retention_rate",
    "week_4_retention_rate", "share_of_signups", "share_of_activated",
})


def project(rows: list[dict], columns: tuple[str, ...]) -> list[dict]:
    """Keep the named columns, and send rates as rounded percentages.

    Rounding here, once, is deliberate: rounding is arithmetic, and a
    model left to do it will occasionally truncate. Nulls stay null, so a
    rate that is not yet measurable never becomes 0. A column missing
    from a row is skipped, since the two segment files differ.
    """
    projected = []
    for row in rows:
        kept = {}
        for key in columns:
            if key not in row:
                continue
            value = row[key]
            if key in RATE_KEYS and isinstance(value, float):
                value = round(value * 100, 1)
            kept[key] = value
        projected.append(kept)
    return projected


def build_metrics() -> dict:
    data = {
        "kpis": read_csv("01_kpi_summary.csv"),
        "funnel": read_csv("02_funnel.csv"),
        "retention": read_csv("03_retention.csv"),
        "segment_activation": read_csv("04_segment_activation.csv"),
        "segment_conversion": read_csv("05_segment_conversion.csv"),
        "feature_adoption": read_csv("06_feature_adoption.csv"),
        "monthly_trends": read_csv("07_monthly_trends.csv"),
        "top_segments": read_csv("08_top_segments.csv"),
    }

    # The full retention grid is 36 rows of which the brief only ever
    # needs the shape. Weeks 1 and 4 carry that: week 1 is the initial
    # return rate, week 4 is the headline KPI.
    retention = [r for r in data["retention"] if r["week_number"] in (1, 4)]

    # The channel x device leaderboard is 15 rows; the extremes are what
    # a brief would cite. Sending all 15 would invite the model to
    # rank-order the middle, which is noise.
    combos = sorted(
        data["top_segments"], key=lambda r: r["activation_rate"], reverse=True
    )

    return {
        "dataset": {
            "synthetic": True,
            "note": (
                "Generated for a portfolio project with a fixed seed. Not "
                "real customer behaviour and not evidence about any real "
                "product."
            ),
            "window": "2025-09-01 to 2026-02-28",
            "eligible_cohort_users": 8234,
        },
        "units": (
            "Every rate, pct_ and share_ field is already a percentage, "
            "rounded to one decimal place. Write 51.6 as 51.6%. Do not "
            "convert, rescale or re-round it. Fields ending _pp are "
            "percentage-point differences."
        ),
        "definitions": DEFINITIONS,
        "kpis": project(data["kpis"], PAYLOAD_COLUMNS["kpis"]),
        "funnel": project(data["funnel"], PAYLOAD_COLUMNS["funnel"]),
        "monthly_trends": project(
            data["monthly_trends"], PAYLOAD_COLUMNS["monthly_trends"]
        ),
        "retention_weeks_1_and_4": project(
            retention, PAYLOAD_COLUMNS["retention"]
        ),
        "segment_activation": project(
            data["segment_activation"], PAYLOAD_COLUMNS["segments"]
        ),
        "segment_conversion": project(
            data["segment_conversion"], PAYLOAD_COLUMNS["segments"]
        ),
        "feature_adoption_early_7_days": project(
            data["feature_adoption"], PAYLOAD_COLUMNS["feature_adoption"]
        ),
        "channel_device_top_3": project(
            combos[:3], PAYLOAD_COLUMNS["combos"]
        ),
        "channel_device_bottom_3": project(
            combos[-3:], PAYLOAD_COLUMNS["combos"]
        ),
        "derived_comparisons": build_derived(data),
    }


# --------------------------------------------------------------------
# Number verification
# --------------------------------------------------------------------

NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def allowed_numbers(metrics: dict) -> set[str]:
    """Every numeric string the model is permitted to write.

    A rate of 0.5159 may legitimately be written as 51.6%, 51.59%, or
    52%, so each numeric value contributes several accepted spellings.
    """
    allowed: set[str] = set()

    def add(value) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        allowed.add(str(value))
        allowed.add(str(abs(value)))
        if isinstance(value, float):
            for places in (0, 1, 2):
                allowed.add(f"{abs(value):.{places}f}")
            if 0 <= abs(value) <= 1:
                percent = abs(value) * 100
                for places in (0, 1, 2):
                    allowed.add(f"{percent:.{places}f}")
        if isinstance(value, int):
            allowed.add(f"{abs(value):,}")

    def walk(node) -> None:
        if isinstance(node, dict):
            for item in node.values():
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            # Numbers also live in text - years in "Sep 2025", the 1.30%
            # in the definitions - and walking only numeric leaves made
            # every one of those look invented.
            for match in NUMBER_PATTERN.finditer(node):
                allowed.add(match.group())
                allowed.add(match.group().replace(",", ""))
        else:
            add(node)

    walk(metrics)
    # Trailing zeros are dropped by writers: 51.60 and 51.6 are the same
    # claim, so accept both spellings of everything collected above.
    allowed |= {n.rstrip("0").rstrip(".") for n in allowed if "." in n}
    return allowed


def verify_numbers(brief: str, metrics: dict) -> list[str]:
    """Return figures in the brief that are not in the input metrics.

    Bare integers below 100 are skipped - they are window lengths and
    week numbers, not statistics. This checks grounding, not coherence:
    it has passed a brief that was truncated mid-sentence.
    """
    permitted = allowed_numbers(metrics)
    unverified = []
    for match in NUMBER_PATTERN.finditer(brief):
        raw = match.group()
        bare = raw.replace(",", "")
        if "." not in bare and float(bare) < 100:
            continue
        candidates = {raw, bare, bare.rstrip("0").rstrip(".")}
        if not candidates & permitted:
            unverified.append(raw)
    return sorted(set(unverified))


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Rough token count, about four characters per token.

    Approximate on purpose: it only has to keep a call inside the
    provider's budget, and it errs high on dense JSON.
    """
    return len(text) // 4


def build_messages(metrics: dict) -> list[dict]:
    """The exact messages sent to the model.

    Same object as outputs/metrics.json, serialised without whitespace -
    indentation costs about a third of the payload's tokens, and only the
    human-read file needs it.
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Product metrics, already calculated:\n"
                + json.dumps(metrics, separators=(",", ":"))
            ),
        },
    ]


def limits_for(model: str) -> dict:
    """Token limits for the provider behind a litellm model id."""
    provider = model.split("/", 1)[0]
    return PROVIDER_LIMITS.get(provider, DEFAULT_LIMITS)


def call_llm(messages: list[dict], model: str, max_tokens: int) -> str:
    from litellm import completion

    response = completion(
        model=model,
        temperature=TEMPERATURE,
        max_tokens=max_tokens,
        messages=messages,
    )
    return response.choices[0].message.content.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build outputs/metrics.json without calling the LLM",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("INSIGHTFLOW_MODEL", DEFAULT_MODEL),
        help=f"litellm model id (default: {DEFAULT_MODEL})",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    metrics = build_metrics()
    metrics_path = OUTPUT_DIR / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n")
    print(f"Wrote {metrics_path.relative_to(ROOT)}")

    limits = limits_for(args.model)
    max_tokens = limits["max_tokens"]
    token_budget = limits["token_budget"]

    messages = build_messages(metrics)
    prompt_tokens = sum(estimate_tokens(m["content"]) for m in messages)
    projected = prompt_tokens + max_tokens
    print(
        f"Estimated tokens: {prompt_tokens} in + up to {max_tokens} out "
        f"= {projected} against a {token_budget} budget for "
        f"{args.model.split('/', 1)[0]}."
    )

    if args.dry_run:
        print("Dry run: skipping the LLM call.")
        return 0

    if projected > token_budget:
        print(
            f"Refusing to send: {projected} estimated tokens exceeds the "
            f"{token_budget} budget for this provider. Trim "
            "PAYLOAD_COLUMNS, or raise the limit in PROVIDER_LIMITS if the "
            "provider genuinely allows more.",
            file=sys.stderr,
        )
        return 5

    load_env(ROOT / ".env")
    provider = args.model.split("/", 1)[0]
    required_key = PROVIDER_KEYS.get(provider)
    if required_key and not os.environ.get(required_key):
        print(
            f"{required_key} is not set, and model '{args.model}' needs it. "
            "Export it, or put it in a .env file in the project root "
            "(.env is gitignored).",
            file=sys.stderr,
        )
        return 2

    print(f"Calling {args.model} ...")
    try:
        brief = call_llm(messages, args.model, max_tokens)
    except Exception as error:  # noqa: BLE001 - surface the provider's message
        print(f"LLM call failed: {error}", file=sys.stderr)
        return 3

    unverified = verify_numbers(brief, metrics)

    header = (
        "# InsightFlow — Analyst Brief\n\n"
        f"Generated by `scripts/generate_ai_brief.py` using `{args.model}`.\n"
        "Every figure below was calculated in SQL and passed to the model "
        "as structured input (`outputs/metrics.json`). The model performed "
        "no calculation and had no database access.\n\n"
        "**The dataset is synthetic.** See `docs/DATA.md`.\n\n---\n\n"
    )
    brief_path = OUTPUT_DIR / "analyst_brief.md"
    brief_path.write_text(header + brief + "\n")
    print(f"Wrote {brief_path.relative_to(ROOT)}")

    if unverified:
        print(
            "\nWARNING: these figures in the brief were not found in the "
            "input metrics:\n  " + "\n  ".join(unverified) +
            "\nCheck each one before publishing the brief.",
            file=sys.stderr,
        )
        return 4

    print("Number check passed: every figure traces back to the input.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
