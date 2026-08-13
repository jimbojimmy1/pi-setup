"""The recursive debate daemon.

One tick = one full round: BULL argues, BEAR attacks, JUDGE rules. The verdict
decides whether the idea recurses into children, gets rewritten, or dies with a
lesson attached.
"""
import json
import os
import random
import signal
import sys
import time

try:
    from . import llm, store
    from .experiments import classify_action, export_work_package
    from .inbox import process_inbox
    from .monitoring import (
        ALLOWED_SOURCES,
        MonitoringError,
        collect_checkout_readiness,
        collect_public_health,
        configured_source_kind,
        monitor_experiment,
        validate_public_https_url,
    )
except ImportError:  # Installed scripts also run directly on the Raspberry Pi.
    import llm
    import store
    from experiments import classify_action, export_work_package
    from inbox import process_inbox
    from monitoring import (
        ALLOWED_SOURCES,
        MonitoringError,
        collect_checkout_readiness,
        collect_public_health,
        configured_source_kind,
        monitor_experiment,
        validate_public_https_url,
    )

HERE = os.path.dirname(os.path.abspath(__file__))


def cfg(key, default, cast=str):
    try:
        return cast(os.environ.get(key, default))
    except (TypeError, ValueError):
        return cast(default)


TICK = cfg("MA_TICK_SECONDS", "900", int)
MAX_ROUNDS = cfg("MA_MAX_ROUNDS", "4", int)
MAX_DEPTH = cfg("MA_MAX_DEPTH", "2", int)
CHILD_FANOUT = cfg("MA_CHILD_FANOUT", "2", int)
MAX_OPEN = cfg("MA_MAX_OPEN", "12", int)
PROMOTE_AT = cfg("MA_PROMOTE_AT", "72", int)
KILL_AT = cfg("MA_KILL_AT", "35", int)
DAILY_USD = cfg("MA_DAILY_USD", "2.00", float)
HORIZON = os.environ.get("MA_HORIZON", "fast").strip().lower()

HORIZON_NOTES = {
    "fast": (
        "PRIORITY THIS RUN — SPEED TO THE FIRST REAL DOLLAR. The operator wants "
        "revenue in weeks, not quarters. Weight time-to-first-dollar and cheap "
        "validation far above defensibility and long-run ceiling. A boring "
        "service that bills a customer this month beats an elegant product that "
        "bills someone next year. Selling the operator's existing skills "
        "directly is a legitimate answer here, not a cop-out — say so if it is "
        "the fastest honest path. Prefer plays whose first dollar needs no new "
        "build, no new account, and no permission from a gatekeeper."
    ),
    "balanced": (
        "PRIORITY THIS RUN — DURABLE MONTHLY INCOME. Weight defensibility and "
        "the long-run ceiling as heavily as speed to the first dollar."
    ),
}

RUNNING = True


def _stop(signum, frame):
    global RUNNING
    RUNNING = False
    log("shutdown signal received; finishing current step")


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_profile():
    try:
        with open(os.path.join(HERE, "profile.json")) as f:
            return json.load(f)
    except Exception as e:
        log(f"could not read profile.json ({e}); using an empty profile")
        return {}


# ===================== prompts =====================

GROUND_RULES = """You are one half of an adversarial pair that hunts for real,
legal ways for one technical person to make money. You run unsupervised, so the
bar for honesty is higher than usual, not lower.

HARD RULES — an idea that touches any of these is dead on arrival, and saying so
is your job:
- Nothing illegal, and nothing needing a licence the operator does not hold
  (investment advice, medical advice, legal advice, money transmission).
- No deception of any kind: no fake reviews, fake scarcity, fake credentials,
  fake testimonials, undisclosed affiliate relationships, or impersonating a
  person or company.
- No spam, no scraping in violation of a site's terms, no circumventing
  paywalls, rate limits, or anti-bot measures.
- No MLM, dropshipping arbitrage built on misleading listings, "AI course"
  schemes, or anything whose revenue comes from other hopefuls rather than from
  a customer with a real problem.
- No plan that depends on the operator's own AI writing content at volume and
  passing it off as human, and none that quietly resells someone else's work.

HONESTY RULES:
- Numbers must be reasoned, not conjured. When you give a figure, say what it is
  derived from and how confident you are. "I do not know" beats a made-up
  number.
- Assume the operator's time is genuinely scarce. A plan needing 40 hours a week
  from someone with 10 is not a plan.
- Money-making ideas mostly fail. Treat a confident kill as a good outcome, not
  a failure of imagination."""


def profile_block(profile):
    return "OPERATOR PROFILE (who this is for):\n" + json.dumps(profile, indent=2)


def lessons_block():
    ls = store.lessons(limit=25)
    if not ls:
        return "PRIOR LESSONS: none yet — this is early in the run."
    lines = [f"- {l['text']}" for l in ls]
    return (
        "PRIOR LESSONS from earlier debates (do not re-propose what these rule "
        "out):\n" + "\n".join(lines)
    )


def board_block():
    titles = store.all_titles()
    if not titles:
        return "IDEAS SO FAR: none."
    lines = [f"- [{s}] {t}" for t, s in titles[-40:]]
    return "IDEAS ALREADY ON THE BOARD (do not duplicate these):\n" + "\n".join(lines)


def system_prompt(profile, role):
    """Stable prefix first (cacheable), volatile board/lessons last."""
    horizon = HORIZON_NOTES.get(HORIZON, HORIZON_NOTES["balanced"])
    return (
        f"{GROUND_RULES}\n\nYOUR ROLE THIS TURN: {role}\n\n{horizon}\n\n"
        f"{profile_block(profile)}\n\n{lessons_block()}\n\n{board_block()}"
    )


BULL_ROLE = """BULL. You argue FOR a specific money-making play and make it as
concrete as you possibly can. Vagueness is the enemy: name the customer, the
price, the mechanism, and the path to the first real dollar. You are optimistic
but not credulous — you are trying to build something that survives an
intelligent attack, not to win a pitch contest."""

BEAR_ROLE = """BEAR. You attack the play in front of you. Your goal is to find
the one thing that actually kills it, not to list twenty small doubts. Be
specific and quantitative: who else already does this, what does the operator's
first month realistically look like, where does the cost or the time actually
land, why would the customer not just do nothing. If the play survives your best
shot, say so plainly — a bear who kills everything is useless."""

JUDGE_ROLE = """JUDGE. You have read both sides and you rule. You are calibrated:
most ideas are mediocre and most scores should land in the middle. You reserve
high scores for plays with evidence behind them and a short path to a paying
customer. You output strict JSON and nothing else."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PROMOTE", "ITERATE", "KILL"]},
        "score": {"type": "integer"},
        "scores": {
            "type": "object",
            "properties": {
                "legality": {"type": "integer"},
                "upfront_cost": {"type": "integer"},
                "time_to_first_dollar": {"type": "integer"},
                "skill_fit": {"type": "integer"},
                "demand_evidence": {"type": "integer"},
                "defensibility": {"type": "integer"},
            },
            "required": [
                "legality",
                "upfront_cost",
                "time_to_first_dollar",
                "skill_fit",
                "demand_evidence",
                "defensibility",
            ],
            "additionalProperties": False,
        },
        "realistic_monthly_usd": {"type": "integer"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "rationale": {"type": "string"},
        "strongest_objection": {"type": "string"},
        "next_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "hours": {"type": "number"},
                    "cost_usd": {"type": "number"},
                },
                "required": ["action", "hours", "cost_usd"],
                "additionalProperties": False,
            },
        },
        "child_questions": {"type": "array", "items": {"type": "string"}},
        "experiment": {
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"},
                        "action_kind": {"type": "string"},
                        "hypothesis": {"type": "string"},
                        "deliverable": {"type": "string"},
                        "metric": {"type": "string"},
                        "measurement_source": {"type": "string"},
                        "window_days": {"type": "integer"},
                        "hours": {"type": "number"},
                        "cost_usd": {"type": "number"},
                        "stop_condition": {"type": "string"},
                    },
                    "required": [
                        "project",
                        "action_kind",
                        "hypothesis",
                        "deliverable",
                        "metric",
                        "measurement_source",
                        "window_days",
                        "hours",
                        "cost_usd",
                        "stop_condition",
                    ],
                    "additionalProperties": False,
                },
                {"type": "object", "maxProperties": 0},
            ]
        },
        "lesson": {"type": "string"},
    },
    "required": [
        "verdict",
        "score",
        "scores",
        "realistic_monthly_usd",
        "confidence",
        "rationale",
        "strongest_objection",
        "next_actions",
        "child_questions",
        "experiment",
        "lesson",
    ],
    "additionalProperties": False,
}

SEED_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "thesis": {"type": "string"},
    },
    "required": ["title", "thesis"],
    "additionalProperties": False,
}

ANGLES = [
    "a productised service sold to a specific trade or small business",
    "a piece of software or hardware the operator can sell more than once",
    "something that turns hardware or data the operator already owns into revenue",
    "a boring, unglamorous local service with real recurring demand",
    "a tool for a niche that is currently served only by spreadsheets",
    "a maintenance or monitoring contract rather than a one-off build",
    "something whose first customer could plausibly be found in one week",
]


# ===================== the round =====================


def clamp(v, lo=0, hi=100):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return lo


class Agent:
    def __init__(self):
        self.profile = load_profile()
        self.backend = llm.pick_backend()
        log(f"LLM backend: {self.backend.name} (model={llm.MODEL})")
        store.set_meta("backend", self.backend.name)
        store.set_meta("model", llm.MODEL)

    def ask(self, role, user, schema=None):
        text, usage = self.backend.complete(
            system_prompt(self.profile, role), user, schema=schema
        )
        store.log_usage(
            usage["backend"],
            usage["model"],
            usage["in_tok"],
            usage["out_tok"],
            usage["cache_read"],
            usage["usd"],
        )
        return text

    # ---------- seeding a new root idea ----------
    def seed_root(self):
        angle = random.choice(ANGLES)
        user = (
            "Propose ONE new money-making play for this operator that is not "
            "already on the board and is not ruled out by the prior lessons.\n\n"
            f"For this proposal, aim at: {angle}.\n\n"
            "Give it a short concrete title (under 12 words) and a thesis of "
            "3-6 sentences covering: who pays, what they get, roughly what it "
            "costs them, and why this operator specifically can deliver it."
        )
        raw = self.ask(BULL_ROLE, user, schema=SEED_SCHEMA)
        data = llm.extract_json(raw)
        title = (data.get("title") or "Untitled play").strip()
        thesis = (data.get("thesis") or "").strip()
        idea_id = store.add_idea(title, thesis=thesis, depth=0)
        log(f"seeded root #{idea_id}: {title}")
        return idea_id

    # ---------- context for a round ----------
    def context_for(self, idea):
        parts = []
        chain = store.ancestors(idea["id"])
        if chain:
            parts.append(
                "THIS IDEA DESCENDS FROM:\n"
                + "\n".join(
                    f"  depth {a['depth']}: {a['title']} (score {a['best_score']})\n"
                    f"    {a['thesis'][:600]}"
                    for a in chain
                )
            )
        if idea["question"]:
            parts.append(
                "THIS IS A FOCUSED SUB-QUESTION of the parent play. Answer it "
                "concretely; do not re-litigate the parent:\n  " + idea["question"]
            )
        prev = store.last_round(idea["id"])
        if prev:
            try:
                pj = json.loads(prev["judge"])
            except Exception:
                pj = {}
            parts.append(
                f"PREVIOUS ROUND ({prev['n']}) ended {prev['verdict']} at score "
                f"{prev['score']}.\n"
                f"  The judge's strongest objection was: "
                f"{pj.get('strongest_objection', 'n/a')}\n"
                f"  The bear's case was:\n{prev['bear'][:1500]}"
            )
        return "\n\n".join(parts) if parts else "(no prior context)"

    # ---------- one full round ----------
    def run_round(self, idea):
        n = idea["rounds"] + 1
        ctx = self.context_for(idea)
        log(f"round {n} on #{idea['id']} (depth {idea['depth']}): {idea['title']}")
        store.set_meta("current", f"#{idea['id']} r{n}: {idea['title']}")

        if n == 1:
            bull_task = (
                f"THE PLAY:\n{idea['title']}\n\n{idea['thesis']}\n\n"
                f"CONTEXT:\n{ctx}\n\n"
                "Make the strongest concrete case for this play. Cover: the exact "
                "customer, what they pay and how often, how the operator delivers "
                "it in the hours available, what the first paying customer looks "
                "like and how they are found, and the single biggest risk you are "
                "knowingly accepting."
            )
        else:
            bull_task = (
                f"THE PLAY:\n{idea['title']}\n\n{idea['thesis']}\n\n"
                f"CONTEXT:\n{ctx}\n\n"
                "The bear landed a hit last round. Rewrite the play so that "
                "objection no longer applies — change the customer, the pricing, "
                "the scope, or the mechanism as needed. If the objection cannot be "
                "engineered around, say so explicitly and explain why the play "
                "should be abandoned. Do not repeat last round's argument."
            )
        bull = self.ask(BULL_ROLE, bull_task)

        bear_task = (
            f"THE PLAY:\n{idea['title']}\n\n{idea['thesis']}\n\n"
            f"CONTEXT:\n{ctx}\n\n"
            f"THE BULL'S CASE:\n{bull}\n\n"
            "Attack it. Lead with the single strongest objection — the one most "
            "likely to make this fail in the real world — and support it with "
            "specifics: who the incumbents are, what the realistic first 90 days "
            "look like, where the hours and dollars actually go, and what would "
            "have to be true for the bull to be right. Then list at most three "
            "secondary concerns. Finish with one line: the cheapest test that "
            "would prove you wrong."
        )
        bear = self.ask(BEAR_ROLE, bear_task)

        judge_task = (
            f"THE PLAY:\n{idea['title']}\n\n{idea['thesis']}\n\n"
            f"CONTEXT:\n{ctx}\n\n"
            f"BULL:\n{bull}\n\nBEAR:\n{bear}\n\n"
            "Rule on this play.\n"
            f"- score: 0-100 overall. PROMOTE at {PROMOTE_AT}+, KILL below "
            f"{KILL_AT}, otherwise ITERATE. This is round {n} of "
            f"{MAX_ROUNDS} — an idea that has not improved by now should be "
            "killed rather than nursed.\n"
            "- scores: 0-100 on each sub-criterion. For upfront_cost and "
            "time_to_first_dollar, HIGHER IS BETTER (100 = free / immediate).\n"
            "- realistic_monthly_usd: honest steady-state monthly profit after "
            "6 months of part-time effort. Be conservative. 0 is a valid answer.\n"
            "- next_actions: 1-3 things the operator could do THIS WEEK, each "
            "small, concrete and verifiable, with honest hours and dollars. Not "
            "'research the market' — say exactly what to do.\n"
            "- child_questions: if and only if you PROMOTE, give up to "
            f"{CHILD_FANOUT} specific unresolved sub-questions that decide "
            "whether this actually works (pricing, first customer, distribution, "
            "delivery cost). Each must be answerable on its own. Empty list "
            "otherwise.\n"
            "- experiment: if and only if you PROMOTE, provide exactly one "
            "bounded experiment. Prefer improving an owned project from the "
            "operator profile over proposing a new business. The metric must "
            "name its observable source, cost_usd must be honest, and the stop "
            "condition must be objective. Propose measurement_source as one of "
            "analytics_readonly, payment_provider_readonly, owner_verified, or "
            "public_http:https://...; configuration, not your output, decides "
            "whether it is trusted. Use an empty object otherwise.\n"
            "- lesson: one durable, transferable sentence for future debates. "
            "Not a restatement of this idea — something that will still be true "
            "for the next twenty."
        )
        raw = self.ask(JUDGE_ROLE, judge_task, schema=JUDGE_SCHEMA)
        judge = llm.extract_json(raw)

        score = clamp(judge.get("score", 0))
        verdict = str(judge.get("verdict", "ITERATE")).upper()
        if verdict not in ("PROMOTE", "ITERATE", "KILL"):
            verdict = "ITERATE"
        # The thresholds are ours, not the model's — enforce them.
        if score >= PROMOTE_AT:
            verdict = "PROMOTE"
        elif score < KILL_AT:
            verdict = "KILL"
        elif verdict == "PROMOTE":
            verdict = "ITERATE"
        judge["verdict"] = verdict
        judge["score"] = score

        store.add_round(idea["id"], n, bull, bear, judge, verdict, score)
        self.apply(idea, n, judge, bull)
        return verdict, score

    # ---------- consequences ----------
    def apply(self, idea, n, judge, bull):
        best = max(idea["best_score"], judge["score"])
        fields = {
            "rounds": n,
            "score": judge["score"],
            "best_score": best,
            "monthly_usd": clamp(judge.get("realistic_monthly_usd", 0), 0, 10_000_000),
            "confidence": str(judge.get("confidence", "low")).lower(),
        }

        store.add_lesson(idea["id"], idea["title"], judge.get("lesson", ""))

        acts = judge.get("next_actions") or []
        if isinstance(acts, list) and acts:
            store.replace_actions(idea["id"], acts[:3])

        verdict = judge["verdict"]
        # Fold the sharpened case back into the thesis so the next round (and any
        # children) build on the rewrite instead of re-reading the original pitch.
        if verdict != "KILL" and n > 1 and bull:
            fields["thesis"] = bull.strip()[:4000]

        if verdict == "PROMOTE":
            fields["status"] = "promoted"
            self.persist_experiment(idea["id"], judge)
            kids = [q for q in (judge.get("child_questions") or []) if str(q).strip()]
            if idea["depth"] < MAX_DEPTH:
                for q in kids[:CHILD_FANOUT]:
                    cid = store.add_idea(
                        title=str(q).strip()[:160],
                        thesis=idea["thesis"],
                        question=str(q).strip(),
                        parent_id=idea["id"],
                        depth=idea["depth"] + 1,
                    )
                    log(f"  -> spawned child #{cid} at depth {idea['depth'] + 1}")
            else:
                log("  -> at max depth; not recursing further")
        elif verdict == "KILL":
            fields["status"] = "killed"
        else:
            fields["status"] = "live" if n < MAX_ROUNDS else "parked"

        store.update_idea(idea["id"], **fields)
        log(f"  verdict {verdict} score {judge['score']} -> {fields['status']}")

    def persist_experiment(self, idea_id, judge):
        if judge.get("verdict") != "PROMOTE":
            return None
        experiment = judge.get("experiment")
        if not isinstance(experiment, dict):
            return None

        text_fields = (
            "project",
            "action_kind",
            "hypothesis",
            "deliverable",
            "metric",
            "stop_condition",
        )
        if any(not str(experiment.get(field, "")).strip() for field in text_fields):
            return None
        try:
            window_days = int(experiment.get("window_days", 0))
            hours = float(experiment.get("hours", 0))
            cost_usd = float(experiment.get("cost_usd", 0))
        except (TypeError, ValueError):
            return None
        if window_days < 1 or hours < 0 or cost_usd < 0:
            return None

        existing = store.find_experiment(
            idea_id,
            experiment["project"],
            experiment["action_kind"],
            experiment["deliverable"],
        )
        if existing:
            return existing["id"]

        autonomy_class = classify_action(experiment["action_kind"], cost_usd)
        if autonomy_class == "REJECTED":
            return None
        proposed_source = str(experiment.get("measurement_source", "")).strip()
        trusted_sources = {
            source.strip()
            for source in os.environ.get(
                "MA_TRUSTED_MEASUREMENT_SOURCES", ""
            ).split(",")
            if source.strip() in ALLOWED_SOURCES
        }
        measurement_source = ""
        if proposed_source.startswith("public_http:"):
            try:
                validate_public_https_url(
                    proposed_source.removeprefix("public_http:")
                )
                measurement_source = proposed_source
            except MonitoringError:
                measurement_source = ""
        elif proposed_source in trusted_sources:
            measurement_source = proposed_source
        experiment_id = store.add_experiment(
            idea_id=idea_id,
            project=experiment["project"],
            action_kind=experiment["action_kind"],
            hypothesis=experiment["hypothesis"],
            deliverable=experiment["deliverable"],
            metric=experiment["metric"],
            stop_condition=experiment["stop_condition"],
            window_days=window_days,
            autonomy_class=autonomy_class,
            hours=hours,
            cost_usd=cost_usd,
            measurement_source=measurement_source,
        )
        store.add_experiment_event(
            experiment_id,
            "ready",
            f"Policy classified this work as {autonomy_class}.",
        )
        return experiment_id

    def monitor_experiments(self):
        monitored = 0
        for experiment in store.list_experiments():
            if experiment["status"] in ("won", "lost"):
                continue
            validated = monitor_experiment(experiment["id"])
            if (
                configured_source_kind(experiment["measurement_source"])
                == "public_http"
                and validated["status"] != "blocked"
            ):
                try:
                    if experiment["metric"] == "public_availability":
                        collect_public_health(experiment["id"])
                    elif experiment["metric"] == "checkout_readiness":
                        collect_checkout_readiness(experiment["id"])
                except MonitoringError:
                    detail = "Public evidence configuration was rejected."
                    store.update_experiment_status(
                        experiment["id"], "blocked", result=detail
                    )
                    store.add_experiment_event(experiment["id"], "blocked", detail)
            monitored += 1
        return monitored

    def bootstrap_owned_health_checks(self):
        existing = {
            (
                experiment["project"],
                experiment["action_kind"],
                experiment["measurement_source"],
            )
            for experiment in store.list_experiments()
        }
        created = 0
        projects = self.profile.get("owned_projects", [])
        if not isinstance(projects, list):
            return 0
        for project in projects:
            if not isinstance(project, dict):
                continue
            name = str(project.get("name", "")).strip()
            url = str(project.get("url", "")).strip()
            proposed_source = f"public_http:{url}"
            if not name or not url:
                continue
            if (name, "public_health_check", proposed_source) in existing:
                continue
            try:
                normalized_url = validate_public_https_url(url)
            except MonitoringError:
                continue
            measurement_source = f"public_http:{normalized_url}"
            key = (name, "public_health_check", measurement_source)
            if key in existing:
                continue
            idea_id = store.add_idea(
                f"{name} public availability",
                thesis=(
                    f"Verify that the owned public project {name} remains "
                    "reachable without treating uptime as traffic, conversion, "
                    "or revenue evidence."
                ),
            )
            experiment_id = store.add_experiment(
                idea_id=idea_id,
                project=name,
                action_kind="public_health_check",
                hypothesis=f"The owned public project {name} remains reachable.",
                deliverable=f"Record bounded HTTPS availability for {name}.",
                metric="public_availability",
                stop_condition="Escalate repeated unavailability; never infer sales.",
                window_days=30,
                autonomy_class="AUTO_LOCAL",
                hours=0,
                cost_usd=0,
                measurement_source=measurement_source,
            )
            store.add_experiment_event(
                experiment_id,
                "ready",
                "Bootstrapped zero-cost public availability monitoring.",
            )
            existing.add(key)
            created += 1
        return created

    def bootstrap_owned_checkout_checks(self):
        existing = {
            (
                experiment["project"],
                experiment["action_kind"],
                experiment["measurement_source"],
            )
            for experiment in store.list_experiments()
        }
        created = 0
        projects = self.profile.get("owned_projects", [])
        if not isinstance(projects, list):
            return 0
        for project in projects:
            if not isinstance(project, dict):
                continue
            name = str(project.get("name", "")).strip()
            url = str(project.get("url", "")).strip()
            proposed_source = f"public_http:{url}"
            if not name or not url:
                continue
            if (name, "checkout_readiness_check", proposed_source) in existing:
                continue
            try:
                normalized_url = validate_public_https_url(url)
            except MonitoringError:
                continue
            measurement_source = f"public_http:{normalized_url}"
            key = (name, "checkout_readiness_check", measurement_source)
            if key in existing:
                continue
            idea_id = store.add_idea(
                f"{name} checkout readiness",
                thesis=(
                    f"Verify that the owned public project {name} exposes a "
                    "recognized checkout destination without opening checkout "
                    "or treating readiness as a sale."
                ),
            )
            experiment_id = store.add_experiment(
                idea_id=idea_id,
                project=name,
                action_kind="checkout_readiness_check",
                hypothesis=f"The owned public project {name} exposes checkout.",
                deliverable=f"Inspect bounded checkout readiness for {name}.",
                metric="checkout_readiness",
                stop_condition="Keep the owner blocker until readiness is verified.",
                window_days=30,
                autonomy_class="AUTO_LOCAL",
                hours=0,
                cost_usd=0,
                measurement_source=measurement_source,
            )
            store.add_experiment_event(
                experiment_id,
                "ready",
                "Bootstrapped zero-cost checkout-readiness monitoring.",
            )
            existing.add(key)
            created += 1
        return created

    def bootstrap_owned_revenue_lanes(self):
        """Prepare a zero-claim destination for explicit owner payment evidence."""
        action_kind = "prepare_verified_revenue_lane"
        measurement_source = "owner_verified"
        existing = {
            (
                experiment["project"],
                experiment["action_kind"],
                experiment["measurement_source"],
            )
            for experiment in store.list_experiments()
        }
        created = 0
        projects = self.profile.get("owned_projects", [])
        if not isinstance(projects, list):
            return 0
        for project in projects:
            if not isinstance(project, dict):
                continue
            name = str(project.get("name", "")).strip()
            key = (name, action_kind, measurement_source)
            if not name or key in existing:
                continue
            idea_id = store.add_idea(
                f"{name} verified revenue evidence",
                thesis=(
                    f"Prepare a local evidence lane for {name} so a real payment "
                    "can be recorded without inferring revenue from traffic or "
                    "checkout readiness."
                ),
            )
            experiment_id = store.add_experiment(
                idea_id=idea_id,
                project=name,
                action_kind=action_kind,
                hypothesis=(
                    f"Explicit owner-verified evidence can measure payments for {name}."
                ),
                deliverable=(
                    f"Accept only explicit owner-verified payment evidence for {name}."
                ),
                metric="verified_payment",
                stop_condition=(
                    "Never infer a payment from availability, checkout readiness, "
                    "or analytics."
                ),
                window_days=3650,
                autonomy_class=classify_action(action_kind, 0),
                hours=0,
                cost_usd=0,
                measurement_source=measurement_source,
            )
            detail = (
                "Prepared a zero-cost local lane; no revenue has been observed. "
                "Only explicit owner-verified evidence may populate it."
            )
            store.update_experiment_status(experiment_id, "measuring", result=detail)
            store.add_experiment_event(experiment_id, "measuring", detail)
            existing.add(key)
            created += 1
        return created

    def process_observation_inbox(self):
        artifact_root = os.environ.get(
            "MA_ARTIFACT_ROOT", os.path.join(HERE, "artifacts")
        )
        try:
            result = process_inbox(artifact_root, limit=25)
        except Exception as exc:
            detail = f"{type(exc).__name__}: observation inbox processing failed"
            store.set_meta("inbox_error", detail)
            log(detail)
            return {
                "accepted": 0,
                "rejected": 0,
                "remaining": 0,
                "error": True,
            }
        store.set_meta("inbox_error", "")
        if result["accepted"] or result["rejected"]:
            log(
                "observation inbox: "
                f"{result['accepted']} accepted, {result['rejected']} rejected, "
                f"{result['remaining']} remaining"
            )
        return result

    def export_next_experiment(self):
        store.recover_stale_experiments()
        claimed = store.claim_experiment()
        if claimed is None:
            return None
        payload = dict(claimed)
        payload["experiment_id"] = claimed["id"]
        payload["next_action"] = claimed["deliverable"]
        artifact_root = os.environ.get(
            "MA_ARTIFACT_ROOT", os.path.join(HERE, "artifacts")
        )
        paths = export_work_package(payload, artifact_root)
        store.add_experiment_event(
            claimed["id"], "exported", f"Work package: {paths.json_path}"
        )
        return claimed

    # ---------- budget ----------
    def over_budget(self):
        spent, _ = store.spend_today()
        if DAILY_USD > 0 and spent >= DAILY_USD:
            store.set_meta("state", "paused-budget")
            store.set_meta(
                "current", f"paused: ${spent:.2f} of ${DAILY_USD:.2f} daily cap used"
            )
            log(f"daily cap reached (${spent:.4f} / ${DAILY_USD:.2f}); idling")
            return True
        return False

    # ---------- one unit of work (thread-safe) ----------
    def unit(self):
        """Debate the best claimable idea, or seed a root if there is none."""
        target = store.claim_target(MAX_ROUNDS)
        if target is None:
            if store.open_count() < MAX_OPEN:
                self.seed_root()
            else:
                store.set_meta("state", "saturated")
                store.set_meta(
                    "current",
                    f"{MAX_OPEN} open ideas — working the queue before seeding more",
                )
                log("no eligible target and the board is full")
            return
        try:
            self.run_round(target)
        except BaseException as e:
            # Never leave a claimed idea stranded in 'working'. Log here rather
            # than only at the burst's end, otherwise a released-and-retried
            # idea just looks like a duplicate round in the log.
            store.release(target["id"], target["rounds"])
            log(
                f"  round on #{target['id']} failed "
                f"({type(e).__name__}: {str(e)[:160]}); released for retry"
            )
            raise

    # ---------- one scheduler tick ----------
    def tick(self):
        if self.over_budget():
            return
        store.set_meta("state", "working")
        self.bootstrap_owned_health_checks()
        self.bootstrap_owned_checkout_checks()
        self.bootstrap_owned_revenue_lanes()
        self.process_observation_inbox()
        self.monitor_experiments()
        if self.export_next_experiment() is not None:
            return
        self.unit()

    # ---------- burst: N rounds back-to-back, K at a time ----------
    def burst(self, n, parallel):
        from concurrent.futures import ThreadPoolExecutor

        store.set_meta("state", "burst")
        log(f"burst: {n} units of work, {parallel} at a time")
        done = errors = 0
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            pending = []
            for _ in range(n):
                if not RUNNING or self.over_budget():
                    break
                pending.append(pool.submit(self.unit))
            for f in pending:
                try:
                    f.result()
                    done += 1
                except Exception as e:
                    errors += 1
                    log(f"unit failed: {type(e).__name__}: {e}")
        log(f"burst finished: {done} ok, {errors} failed")
        store.set_meta("state", "idle")
        return errors


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Money agent debate daemon")
    ap.add_argument(
        "--burst",
        type=int,
        default=0,
        metavar="N",
        help="run N rounds back-to-back and exit (skips the tick delay)",
    )
    ap.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="K",
        help="debate K ideas concurrently (burst mode only)",
    )
    args = ap.parse_args()

    store.init()
    freed = store.release_stale()
    if freed:
        log(f"recovered {freed} idea(s) left mid-round by a previous process")
    store.set_meta("started_at", time.time())
    store.set_meta("pid", os.getpid())
    agent = Agent()

    if args.burst > 0:
        errors = agent.burst(args.burst, max(1, args.parallel))
        return 1 if errors and errors >= args.burst else 0

    log(f"loop starting: one round every {TICK}s, daily cap ${DAILY_USD:.2f}")

    while RUNNING:
        started = time.time()
        try:
            agent.tick()
        except llm.LLMError as e:
            log(f"LLM error: {e}")
            store.set_meta("state", "llm-error")
            store.set_meta("current", str(e)[:300])
        except Exception as e:  # a daemon that dies on one bad round is useless
            log(f"tick failed: {type(e).__name__}: {e}")
            store.set_meta("state", "error")
            store.set_meta("current", f"{type(e).__name__}: {e}"[:300])
        store.set_meta("last_tick", time.time())
        store.set_meta("next_tick", time.time() + TICK)

        # Sleep in slices so SIGTERM lands promptly.
        elapsed = time.time() - started
        remaining = max(5.0, TICK - elapsed)
        while RUNNING and remaining > 0:
            time.sleep(min(2.0, remaining))
            remaining -= 2.0

    store.set_meta("state", "stopped")
    log("stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
