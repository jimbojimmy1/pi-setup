#!/bin/bash
# ================================================================
#  MONEY AGENT — recursive two-agent debate engine (:8086)
# ================================================================
#  A second coworker that never logs off. Two agents argue, a
#  judge rules, and the surviving ideas recurse into sharper
#  sub-questions until they become a concrete to-do list.
#
#    BULL    proposes / sharpens a money-making play
#    BEAR    attacks it — cost, legality, saturation, real demand
#    JUDGE   scores it and rules: PROMOTE / ITERATE / KILL
#
#  PROMOTE  -> the play splits into child questions, each debated
#              recursively one level deeper (pricing, first
#              customer, distribution) — that's the recursion
#  ITERATE  -> BULL rewrites it against BEAR's best shot, round++
#  KILL     -> a lesson is extracted and fed to every future
#              debate, so it stops re-proposing dead ends
#
#  Two services:
#    money-agent      the debate daemon (runs forever)
#    money-agent-web  dashboard on :8086
#
#  WHAT IT DOES:  finds, stress-tests and ranks money-making
#                 plays, and keeps an ACTION QUEUE of the next
#                 concrete steps with hours + dollars attached.
#  WHAT IT DOESN'T: transact, spend, sell, or collect money. No
#                 software can do that without your accounts and
#                 your signature. The action queue is your part.
#
#  LLM backend, in order of preference:
#    1. Anthropic API   (ANTHROPIC_API_KEY in config.env)
#    2. claude CLI      (if Claude Code is installed)
#    3. dry-run         (no LLM — service still runs, clearly
#                        labelled, so you can see the machinery)
# ================================================================

set -e

APP_DIR="${MONEY_AGENT_DIR:-$HOME/money-agent}"
PORT=8086

echo "[1/7] Installing deps..."
if [ "${MA_SKIP_APT:-0}" != "1" ]; then
  sudo apt-get install -y -qq python3-flask python3-pip
  # Raspberry Pi OS Bookworm+ is PEP-668 managed; --break-system-packages is
  # the supported way to add a pure-python lib system-wide.
  pip3 install --quiet --upgrade --break-system-packages anthropic 2>/dev/null \
    || pip3 install --quiet --upgrade anthropic 2>/dev/null \
    || echo "    (!) anthropic SDK not installed — will use claude CLI or dry-run"
fi

mkdir -p "$APP_DIR/templates"

echo "[2/7] Writing config + operator profile..."

# ---- config.env (systemd EnvironmentFile format: KEY=value, no 'export') ----
if [ ! -f "$APP_DIR/config.env" ]; then
cat > "$APP_DIR/config.env" << 'CFGEOF'
# ---- LLM ----
# Paste your key here to use the Anthropic API (best quality, costs money).
# Leave blank to fall back to the `claude` CLI, then to dry-run mode.
ANTHROPIC_API_KEY=
MA_MODEL=claude-opus-5
MA_EFFORT=medium
MA_MAX_TOKENS=12000

# ---- money guard ----
# Hard ceiling on LLM spend per UTC day. The daemon pauses itself when hit.
MA_DAILY_USD=2.00

# ---- pace ----
MA_TICK_SECONDS=900         # one debate round every 15 min (~96/day)

# ---- debate shape ----
MA_MAX_ROUNDS=4             # ITERATE attempts before an idea is parked
MA_MAX_DEPTH=2              # how deep the recursion goes (0=root)
MA_CHILD_FANOUT=2           # child questions spawned per PROMOTE
MA_MAX_OPEN=12              # open ideas before it stops seeding new roots
MA_PROMOTE_AT=72            # judge score needed to PROMOTE
MA_KILL_AT=35               # judge score below which an idea is KILLed
CFGEOF
chmod 600 "$APP_DIR/config.env"
echo "    wrote config.env"
else
echo "    config.env exists — left alone"
fi

# ---- profile.json: who the agent is earning for. EDIT THIS. ----
if [ ! -f "$APP_DIR/profile.json" ]; then
cat > "$APP_DIR/profile.json" << 'PROFEOF'
{
  "location": "St. Louis, MO",
  "hours_per_week": 10,
  "starting_capital_usd": 500,
  "skills": [
    "Python and Linux",
    "Raspberry Pi / embedded hardware",
    "cameras, streaming, computer vision",
    "home automation and networking",
    "building small web apps and dashboards"
  ],
  "assets": [
    "a fleet of Raspberry Pis running 24/7",
    "cameras and an SDR",
    "a home lab with static networking",
    "an existing habit of shipping small working projects"
  ],
  "constraints": [
    "no employees and no co-founder",
    "no physical inventory that has to be warehoused",
    "nothing requiring a license I do not hold",
    "no single upfront spend over $500 without my approval",
    "must survive being run 10 hours a week alongside a day job"
  ],
  "goal": "Build to $2,000/month of durable, mostly-passive income within 12 months, starting from skills and hardware I already have.",
  "notes": "Prefers technical products and services over content or audience plays. Hates anything that needs daily manual grinding."
}
PROFEOF
echo "    wrote profile.json  <-- EDIT THIS, it steers everything"
else
echo "    profile.json exists — left alone"
fi

echo "[3/7] Writing store.py..."
cat > "$APP_DIR/store.py" << 'PYEOF'
"""SQLite store. Two processes (daemon + web) share it, so WAL + busy_timeout."""
import json
import os
import sqlite3
import threading
import time

DB = os.environ.get(
    "MA_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "money.db")
)
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS ideas(
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  parent_id   INTEGER,
  depth       INTEGER NOT NULL DEFAULT 0,
  title       TEXT    NOT NULL,
  thesis      TEXT    NOT NULL DEFAULT '',
  question    TEXT    NOT NULL DEFAULT '',
  status      TEXT    NOT NULL DEFAULT 'pending',
  score       INTEGER NOT NULL DEFAULT 0,
  best_score  INTEGER NOT NULL DEFAULT 0,
  monthly_usd INTEGER NOT NULL DEFAULT 0,
  confidence  TEXT    NOT NULL DEFAULT 'low',
  rounds      INTEGER NOT NULL DEFAULT 0,
  created_at  REAL    NOT NULL,
  updated_at  REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS rounds(
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id    INTEGER NOT NULL,
  n          INTEGER NOT NULL,
  bull       TEXT    NOT NULL DEFAULT '',
  bear       TEXT    NOT NULL DEFAULT '',
  judge      TEXT    NOT NULL DEFAULT '{}',
  verdict    TEXT    NOT NULL DEFAULT '',
  score      INTEGER NOT NULL DEFAULT 0,
  created_at REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS actions(
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id    INTEGER NOT NULL,
  action     TEXT    NOT NULL,
  hours      REAL    NOT NULL DEFAULT 0,
  cost_usd   REAL    NOT NULL DEFAULT 0,
  done       INTEGER NOT NULL DEFAULT 0,
  created_at REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS lessons(
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id    INTEGER,
  title      TEXT    NOT NULL DEFAULT '',
  text       TEXT    NOT NULL,
  created_at REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS usage(
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         REAL    NOT NULL,
  day        TEXT    NOT NULL,
  backend    TEXT    NOT NULL,
  model      TEXT    NOT NULL,
  in_tok     INTEGER NOT NULL DEFAULT 0,
  out_tok    INTEGER NOT NULL DEFAULT 0,
  cache_read INTEGER NOT NULL DEFAULT 0,
  usd        REAL    NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_rounds_idea ON rounds(idea_id);
CREATE INDEX IF NOT EXISTS idx_actions_idea ON actions(idea_id);
CREATE INDEX IF NOT EXISTS idx_usage_day ON usage(day);
"""


def conn():
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(DB, timeout=30.0)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        c.execute("PRAGMA synchronous=NORMAL")
        _local.c = c
    return c


def init():
    c = conn()
    c.executescript(SCHEMA)
    c.commit()


def utc_day():
    return time.strftime("%Y-%m-%d", time.gmtime())


# ---------- meta ----------
def set_meta(k, v):
    c = conn()
    c.execute(
        "INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (k, str(v)),
    )
    c.commit()


def get_meta(k, default=None):
    r = conn().execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


# ---------- ideas ----------
def add_idea(title, thesis="", question="", parent_id=None, depth=0):
    now = time.time()
    c = conn()
    cur = c.execute(
        "INSERT INTO ideas(parent_id,depth,title,thesis,question,status,created_at,updated_at)"
        " VALUES(?,?,?,?,?,'pending',?,?)",
        (parent_id, depth, title.strip()[:200], thesis.strip(), question.strip(), now, now),
    )
    c.commit()
    return cur.lastrowid


def get_idea(i):
    r = conn().execute("SELECT * FROM ideas WHERE id=?", (i,)).fetchone()
    return dict(r) if r else None


def update_idea(i, **kw):
    if not kw:
        return
    kw["updated_at"] = time.time()
    sets = ",".join(f"{k}=?" for k in kw)
    c = conn()
    c.execute(f"UPDATE ideas SET {sets} WHERE id=?", (*kw.values(), i))
    c.commit()


def next_target(max_rounds):
    """The idea most deserving of the next debate round.

    Shallow before deep (bank the fundamentals first), fewest rounds first
    (don't starve anything), then most promising.
    """
    r = conn().execute(
        "SELECT * FROM ideas WHERE status IN ('pending','live') AND rounds < ?"
        " ORDER BY depth ASC, rounds ASC, best_score DESC, id ASC LIMIT 1",
        (max_rounds,),
    ).fetchone()
    return dict(r) if r else None


def open_count():
    return conn().execute(
        "SELECT COUNT(*) n FROM ideas WHERE status IN ('pending','live')"
    ).fetchone()["n"]


def all_titles():
    return [
        (r["title"], r["status"])
        for r in conn().execute("SELECT title,status FROM ideas ORDER BY id").fetchall()
    ]


def leaderboard(limit=40):
    rows = conn().execute(
        "SELECT * FROM ideas WHERE status != 'killed'"
        " ORDER BY best_score DESC, monthly_usd DESC, id ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def killed(limit=20):
    rows = conn().execute(
        "SELECT * FROM ideas WHERE status='killed' ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def ancestors(i):
    out, seen = [], set()
    cur = get_idea(i)
    while cur and cur["parent_id"] and cur["parent_id"] not in seen:
        seen.add(cur["parent_id"])
        cur = get_idea(cur["parent_id"])
        if cur:
            out.append(cur)
    return list(reversed(out))


# ---------- rounds ----------
def add_round(idea_id, n, bull, bear, judge, verdict, score):
    now = time.time()
    c = conn()
    c.execute(
        "INSERT INTO rounds(idea_id,n,bull,bear,judge,verdict,score,created_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (idea_id, n, bull, bear, json.dumps(judge), verdict, score, now),
    )
    c.commit()


def rounds_for(idea_id):
    rows = conn().execute(
        "SELECT * FROM rounds WHERE idea_id=? ORDER BY n ASC", (idea_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def last_round(idea_id):
    r = conn().execute(
        "SELECT * FROM rounds WHERE idea_id=? ORDER BY n DESC LIMIT 1", (idea_id,)
    ).fetchone()
    return dict(r) if r else None


def recent_rounds(limit=12):
    rows = conn().execute(
        "SELECT r.*, i.title FROM rounds r JOIN ideas i ON i.id=r.idea_id"
        " ORDER BY r.created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- actions ----------
def replace_actions(idea_id, actions):
    c = conn()
    c.execute("DELETE FROM actions WHERE idea_id=? AND done=0", (idea_id,))
    now = time.time()
    for a in actions:
        c.execute(
            "INSERT INTO actions(idea_id,action,hours,cost_usd,done,created_at)"
            " VALUES(?,?,?,?,0,?)",
            (idea_id, str(a.get("action", ""))[:1000], float(a.get("hours", 0) or 0),
             float(a.get("cost_usd", 0) or 0), now),
        )
    c.commit()


def action_queue(limit=25):
    rows = conn().execute(
        "SELECT a.*, i.title, i.best_score, i.status AS idea_status FROM actions a"
        " JOIN ideas i ON i.id=a.idea_id"
        " WHERE a.done=0 AND i.status IN ('promoted','live','pending','parked')"
        " ORDER BY i.best_score DESC, a.cost_usd ASC, a.hours ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def toggle_action(aid):
    c = conn()
    c.execute("UPDATE actions SET done = 1 - done WHERE id=?", (aid,))
    c.commit()


# ---------- lessons ----------
def add_lesson(idea_id, title, text):
    text = (text or "").strip()
    if not text:
        return
    c = conn()
    dup = c.execute("SELECT id FROM lessons WHERE text=?", (text,)).fetchone()
    if dup:
        return
    c.execute(
        "INSERT INTO lessons(idea_id,title,text,created_at) VALUES(?,?,?,?)",
        (idea_id, title, text, time.time()),
    )
    c.commit()


def lessons(limit=30):
    rows = conn().execute(
        "SELECT * FROM lessons ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- usage / spend ----------
def log_usage(backend, model, in_tok, out_tok, cache_read, usd):
    c = conn()
    c.execute(
        "INSERT INTO usage(ts,day,backend,model,in_tok,out_tok,cache_read,usd)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (time.time(), utc_day(), backend, model, in_tok, out_tok, cache_read, usd),
    )
    c.commit()


def spend_today():
    r = conn().execute(
        "SELECT COALESCE(SUM(usd),0) s, COUNT(*) n FROM usage WHERE day=?", (utc_day(),)
    ).fetchone()
    return float(r["s"]), int(r["n"])


def spend_total():
    r = conn().execute("SELECT COALESCE(SUM(usd),0) s FROM usage").fetchone()
    return float(r["s"])


def counts():
    rows = conn().execute(
        "SELECT status, COUNT(*) n FROM ideas GROUP BY status"
    ).fetchall()
    out = {r["status"]: r["n"] for r in rows}
    out["rounds"] = conn().execute("SELECT COUNT(*) n FROM rounds").fetchone()["n"]
    return out
PYEOF

echo "[4/7] Writing llm.py..."
cat > "$APP_DIR/llm.py" << 'PYEOF'
"""LLM backend layer.

Prefers the Anthropic API, falls back to the `claude` CLI, then to a dry-run
stub so the daemon still runs (and says so loudly) with no credentials.
"""
import json
import os
import re
import shutil
import subprocess

MODEL = os.environ.get("MA_MODEL", "claude-opus-5").strip() or "claude-opus-5"
EFFORT = os.environ.get("MA_EFFORT", "medium").strip() or "medium"
MAX_TOKENS = int(os.environ.get("MA_MAX_TOKENS", "12000"))

# List price, USD per million tokens (input, output). Used only for the local
# spend guard — it is an estimate, your invoice is the source of truth.
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


class LLMError(RuntimeError):
    pass


def extract_json(text):
    """Pull the first complete JSON object out of a model response."""
    if not text:
        raise LLMError("empty response")
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    start = t.find("{")
    if start < 0:
        raise LLMError("no JSON object in response")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(t[start : i + 1])
    raise LLMError("unterminated JSON object")


# --------------------------------------------------------------------------
class APIBackend:
    name = "anthropic-api"

    def __init__(self):
        import anthropic  # noqa: F401  (import error => backend unavailable)

        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        # Server-side refusal fallback keeps one declined request from
        # stalling the loop; dropped automatically if the API rejects it.
        self.use_fallbacks = True

    def _output_config(self, schema):
        oc = {"effort": EFFORT}
        if schema:
            oc["format"] = {"type": "json_schema", "schema": schema}
        return oc

    def complete(self, system, user, schema=None):
        system_blocks = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        kw = dict(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_blocks,
            output_config=self._output_config(schema),
            messages=[{"role": "user", "content": user}],
        )
        if self.use_fallbacks:
            try:
                resp = self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                    **kw,
                )
            except self._anthropic.BadRequestError:
                # Beta not available on this key/SDK — stop trying.
                self.use_fallbacks = False
                resp = self.client.messages.create(**kw)
        else:
            resp = self.client.messages.create(**kw)

        if getattr(resp, "stop_reason", None) == "refusal":
            det = getattr(resp, "stop_details", None)
            cat = getattr(det, "category", None) if det else None
            raise LLMError(f"model declined the request (category={cat})")

        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )
        u = resp.usage
        in_tok = getattr(u, "input_tokens", 0) or 0
        out_tok = getattr(u, "output_tokens", 0) or 0
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        pin, pout = PRICES.get(MODEL, (5.0, 25.0))
        usd = (
            in_tok * pin
            + cache_write * pin * 1.25
            + cache_read * pin * 0.1
            + out_tok * pout
        ) / 1_000_000.0
        return text, {
            "backend": self.name,
            "model": MODEL,
            "in_tok": in_tok,
            "out_tok": out_tok,
            "cache_read": cache_read,
            "usd": usd,
        }


# --------------------------------------------------------------------------
class CLIBackend:
    """Uses an installed Claude Code CLI. Billed to that subscription, so the
    local spend guard cannot see the cost — it records 0."""

    name = "claude-cli"

    def __init__(self):
        self.bin = shutil.which("claude")
        if not self.bin:
            raise LLMError("claude CLI not found")

    def complete(self, system, user, schema=None):
        prompt = system + "\n\n=== TASK ===\n\n" + user
        if schema:
            prompt += (
                "\n\nRespond with ONLY a single JSON object matching this schema. "
                "No prose, no code fence:\n" + json.dumps(schema)
            )
        try:
            p = subprocess.run(
                [self.bin, "-p", prompt, "--model", MODEL, "--output-format", "text"],
                capture_output=True,
                text=True,
                timeout=900,
            )
        except subprocess.TimeoutExpired as e:
            raise LLMError("claude CLI timed out") from e
        if p.returncode != 0:
            raise LLMError(f"claude CLI failed: {p.stderr.strip()[:300]}")
        return p.stdout.strip(), {
            "backend": self.name,
            "model": MODEL,
            "in_tok": 0,
            "out_tok": 0,
            "cache_read": 0,
            "usd": 0.0,
        }


# --------------------------------------------------------------------------
class DryRunBackend:
    """No credentials. Keeps the machinery visibly turning without pretending
    the output means anything."""

    name = "dry-run"

    def complete(self, system, user, schema=None):
        if schema and "title" in schema.get("properties", {}):
            return (
                json.dumps(
                    {
                        "title": "DRY RUN - no LLM backend configured",
                        "thesis": "Nothing has been evaluated. Add an "
                        "ANTHROPIC_API_KEY to config.env, or install the claude "
                        "CLI, then restart the money-agent service.",
                    }
                ),
                self._usage(),
            )
        if schema:
            payload = {
                "verdict": "ITERATE",
                "score": 50,
                "scores": {
                    "legality": 50,
                    "upfront_cost": 50,
                    "time_to_first_dollar": 50,
                    "skill_fit": 50,
                    "demand_evidence": 50,
                    "defensibility": 50,
                },
                "realistic_monthly_usd": 0,
                "confidence": "low",
                "rationale": "DRY RUN — no LLM backend configured. Add an "
                "ANTHROPIC_API_KEY to config.env, or install the claude CLI.",
                "strongest_objection": "No model is running, so nothing has "
                "actually been evaluated.",
                "next_actions": [
                    {
                        "action": "Put an Anthropic API key in "
                        "~/money-agent/config.env, then: sudo systemctl restart "
                        "money-agent",
                        "hours": 0.1,
                        "cost_usd": 0,
                    }
                ],
                "child_questions": [],
                "lesson": "A debate with no model in it is just a cron job.",
            }
            return json.dumps(payload), self._usage()
        return (
            "DRY RUN — no LLM backend configured. This is placeholder text so "
            "you can see the pipeline running end to end.",
            self._usage(),
        )

    def _usage(self):
        return {
            "backend": self.name,
            "model": "none",
            "in_tok": 0,
            "out_tok": 0,
            "cache_read": 0,
            "usd": 0.0,
        }


def pick_backend():
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        try:
            return APIBackend()
        except Exception as e:  # SDK missing, bad key shape, etc.
            print(f"[llm] API backend unavailable ({e}); trying claude CLI", flush=True)
    try:
        return CLIBackend()
    except Exception:
        pass
    return DryRunBackend()
PYEOF

echo "[5/7] Writing agent.py (the debate loop)..."
cat > "$APP_DIR/agent.py" << 'PYEOF'
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

import llm
import store

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
    return (
        f"{GROUND_RULES}\n\nYOUR ROLE THIS TURN: {role}\n\n"
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

    # ---------- one scheduler tick ----------
    def tick(self):
        spent, calls = store.spend_today()
        if DAILY_USD > 0 and spent >= DAILY_USD:
            store.set_meta("state", "paused-budget")
            store.set_meta(
                "current", f"paused: ${spent:.2f} of ${DAILY_USD:.2f} daily cap used"
            )
            log(f"daily cap reached (${spent:.4f} / ${DAILY_USD:.2f}); idling")
            return

        store.set_meta("state", "working")
        target = store.next_target(MAX_ROUNDS)
        if target is None:
            if store.open_count() < MAX_OPEN:
                self.seed_root()
            else:
                store.set_meta("state", "saturated")
                store.set_meta(
                    "current",
                    f"{MAX_OPEN} open ideas — working the queue before seeding more",
                )
                log("no eligible target and the board is full; idling this tick")
            return
        self.run_round(target)


def main():
    store.init()
    store.set_meta("started_at", time.time())
    store.set_meta("pid", os.getpid())
    agent = Agent()
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
PYEOF

echo "[6/7] Writing app.py + dashboard..."
cat > "$APP_DIR/app.py" << 'PYEOF'
"""Dashboard for the money agent."""
import json
import os
import time

from flask import Flask, jsonify, render_template, request

import store

app = Flask(__name__)
DAILY_USD = float(os.environ.get("MA_DAILY_USD", "2.00") or 0)
_ready = False


@app.before_request
def _ensure_db():
    global _ready
    if not _ready:
        store.init()
        _ready = True


def ago(ts):
    if not ts:
        return "never"
    d = max(0, time.time() - float(ts))
    if d < 60:
        return f"{int(d)}s ago"
    if d < 3600:
        return f"{int(d // 60)}m ago"
    if d < 86400:
        return f"{int(d // 3600)}h ago"
    return f"{int(d // 86400)}d ago"


@app.route("/")
def index():
    return render_template("index.html", port=8086)


@app.route("/api/state")
def api_state():
    spent, calls = store.spend_today()
    c = store.counts()
    return jsonify(
        {
            "state": store.get_meta("state", "starting"),
            "current": store.get_meta("current", ""),
            "backend": store.get_meta("backend", "?"),
            "model": store.get_meta("model", "?"),
            "last_tick": ago(store.get_meta("last_tick")),
            "next_tick_in": max(
                0, int(float(store.get_meta("next_tick", 0) or 0) - time.time())
            ),
            "spend_today": round(spent, 4),
            "spend_total": round(store.spend_total(), 4),
            "daily_cap": DAILY_USD,
            "calls_today": calls,
            "counts": c,
            "leaderboard": store.leaderboard(),
            "actions": store.action_queue(),
            "recent": [
                {
                    "id": r["id"],
                    "idea_id": r["idea_id"],
                    "title": r["title"],
                    "n": r["n"],
                    "verdict": r["verdict"],
                    "score": r["score"],
                    "ago": ago(r["created_at"]),
                }
                for r in store.recent_rounds()
            ],
            "killed": store.killed(),
            "lessons": store.lessons(limit=15),
        }
    )


@app.route("/api/idea/<int:idea_id>")
def api_idea(idea_id):
    idea = store.get_idea(idea_id)
    if not idea:
        return jsonify({"error": "not found"}), 404
    rounds = []
    for r in store.rounds_for(idea_id):
        try:
            judge = json.loads(r["judge"])
        except Exception:
            judge = {}
        rounds.append(
            {
                "n": r["n"],
                "bull": r["bull"],
                "bear": r["bear"],
                "judge": judge,
                "verdict": r["verdict"],
                "score": r["score"],
                "ago": ago(r["created_at"]),
            }
        )
    return jsonify({"idea": idea, "rounds": rounds})


@app.route("/api/action/<int:action_id>/toggle", methods=["POST"])
def api_toggle(action_id):
    store.toggle_action(action_id)
    return jsonify({"ok": True})


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "state": store.get_meta("state", "unknown")})


if __name__ == "__main__":
    store.init()
    app.run(host="0.0.0.0", port=8086, threaded=True)
PYEOF

cat > "$APP_DIR/templates/index.html" << 'HTMLEOF'
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MONEY AGENT</title>
<style>
:root{--bg:#0d0803;--hal:#ff1a1a;--amber:#ffb000;--gold:#d4a017;--cream:#f4ddb6;--teal:#2ec4b6;--dim:#8a7350;}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:radial-gradient(ellipse at 50% 0%,#160d04,var(--bg) 70%);color:var(--cream);
  font-family:'IBM Plex Mono',ui-monospace,Menlo,Consolas,monospace;min-height:100vh;padding:16px;font-size:14px;}
body::after{content:"";position:fixed;inset:0;z-index:50;pointer-events:none;
  background:repeating-linear-gradient(0deg,rgba(0,0,0,.16) 0 1px,transparent 1px 3px);}
a{color:var(--teal);text-decoration:none;}
h1{font-size:20px;letter-spacing:.3em;color:var(--gold);}
h2{font-size:12px;letter-spacing:.25em;color:var(--gold);margin-bottom:10px;
  border-bottom:1px solid rgba(212,160,23,.35);padding-bottom:5px;}
.panel{background:rgba(13,8,3,.62);border:1px solid rgba(212,160,23,.5);
  outline:1px solid rgba(212,160,23,.2);outline-offset:3px;padding:14px;margin-bottom:22px;}
header{display:flex;flex-wrap:wrap;gap:14px;align-items:baseline;justify-content:space-between;margin-bottom:22px;}
.stats{display:flex;flex-wrap:wrap;gap:18px;font-size:12px;color:var(--dim);}
.stats b{color:var(--cream);}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:22px;}
table{width:100%;border-collapse:collapse;}
td,th{padding:6px 8px;text-align:left;vertical-align:top;border-bottom:1px solid rgba(212,160,23,.15);}
th{font-size:10px;letter-spacing:.18em;color:var(--dim);font-weight:normal;}
.score{font-weight:bold;color:var(--amber);}
.pill{font-size:10px;letter-spacing:.12em;padding:2px 6px;border:1px solid currentColor;white-space:nowrap;}
.PROMOTE,.promoted{color:var(--teal);}
.KILL,.killed{color:var(--hal);}
.ITERATE,.live{color:var(--amber);}
.pending{color:var(--dim);}
.parked{color:var(--dim);}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--teal);margin-right:7px;
  animation:pulse 2s infinite;}
.dot.bad{background:var(--hal);}.dot.warn{background:var(--amber);}
@keyframes pulse{50%{opacity:.25;}}
.bar{height:5px;background:rgba(212,160,23,.16);margin-top:5px;}
.bar i{display:block;height:100%;background:var(--amber);}
.act{display:flex;gap:9px;align-items:flex-start;padding:8px 0;border-bottom:1px solid rgba(212,160,23,.15);}
.act input{margin-top:3px;accent-color:var(--amber);cursor:pointer;flex-shrink:0;}
.act .meta{font-size:10px;color:var(--dim);letter-spacing:.1em;}
.muted{color:var(--dim);font-size:11px;line-height:1.6;}
.clickable{cursor:pointer;}
.clickable:hover td{background:rgba(212,160,23,.07);}
#modal{position:fixed;inset:0;background:rgba(0,0,0,.86);z-index:100;display:none;overflow-y:auto;padding:32px 16px;}
#modal .inner{max-width:900px;margin:0 auto;background:var(--bg);border:1px solid var(--gold);padding:22px;}
#modal pre{white-space:pre-wrap;font-family:inherit;font-size:13px;line-height:1.65;margin:8px 0 20px;}
.role{font-size:11px;letter-spacing:.2em;color:var(--gold);margin-top:18px;}
.close{float:right;color:var(--hal);cursor:pointer;letter-spacing:.2em;}
footer{margin-top:28px;padding-top:14px;border-top:1px solid rgba(212,160,23,.25);}
</style>
</head>
<body>

<header>
  <div>
    <h1>◈ MONEY AGENT</h1>
    <div class="muted" id="status" style="margin-top:6px">connecting…</div>
  </div>
  <div class="stats">
    <span>BACKEND <b id="backend">–</b></span>
    <span>SPEND TODAY <b id="spend">–</b></span>
    <span>ALL TIME <b id="total">–</b></span>
    <span>ROUNDS <b id="rounds">–</b></span>
    <span>NEXT <b id="next">–</b></span>
  </div>
</header>

<div class="panel">
  <h2>▸ ACTION QUEUE — your part</h2>
  <div id="actions"><span class="muted">nothing yet</span></div>
</div>

<div class="grid">
  <div class="panel">
    <h2>▸ LEADERBOARD</h2>
    <table><thead><tr><th>score</th><th>idea</th><th>$/mo</th><th>state</th></tr></thead>
    <tbody id="board"></tbody></table>
  </div>

  <div class="panel">
    <h2>▸ LIVE DEBATE</h2>
    <table><thead><tr><th>when</th><th>idea</th><th>rd</th><th>verdict</th></tr></thead>
    <tbody id="recent"></tbody></table>
  </div>

  <div class="panel">
    <h2>▸ LESSONS LEARNED</h2>
    <div id="lessons" class="muted"></div>
  </div>

  <div class="panel">
    <h2>▸ KILL LOG</h2>
    <table><tbody id="killed"></tbody></table>
  </div>
</div>

<footer class="muted">
  Two agents argue, a judge rules, survivors recurse into sharper sub-questions.
  This engine finds, stress-tests and ranks plays — it does not transact, spend or
  earn on its own. The action queue is where you come in.
</footer>

<div id="modal"><div class="inner">
  <span class="close" onclick="document.getElementById('modal').style.display='none'">CLOSE ✕</span>
  <div id="modalbody"></div>
</div></div>

<script>
const esc = s => String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

async function poll(){
  let d;
  try{ d = await (await fetch('/api/state')).json(); }
  catch(e){ document.getElementById('status').textContent='dashboard cannot reach the store'; return; }

  const bad = ['error','llm-error','stopped'].includes(d.state);
  const warn = String(d.state).startsWith('paused') || d.state==='saturated';
  document.getElementById('status').innerHTML =
    `<span class="dot ${bad?'bad':warn?'warn':''}"></span>${esc(d.state)} · ${esc(d.current||'—')} · last tick ${esc(d.last_tick)}`;
  document.getElementById('backend').textContent = d.backend + ' / ' + d.model;
  document.getElementById('spend').textContent = '$'+d.spend_today.toFixed(2)+' / $'+d.daily_cap.toFixed(2);
  document.getElementById('total').textContent = '$'+d.spend_total.toFixed(2);
  document.getElementById('rounds').textContent = d.counts.rounds ?? 0;
  document.getElementById('next').textContent = d.next_tick_in>0 ? d.next_tick_in+'s' : 'now';

  document.getElementById('actions').innerHTML = d.actions.length ? d.actions.map(a=>`
    <div class="act">
      <input type="checkbox" onchange="toggle(${a.id})">
      <div>
        <div>${esc(a.action)}</div>
        <div class="meta">${a.hours}h · $${a.cost_usd} · from “${esc(a.title)}” (score ${a.best_score})</div>
      </div>
    </div>`).join('') : '<span class="muted">no actions yet — the agents are still arguing</span>';

  document.getElementById('board').innerHTML = d.leaderboard.map(i=>`
    <tr class="clickable" onclick="openIdea(${i.id})">
      <td class="score">${i.best_score}<div class="bar"><i style="width:${i.best_score}%"></i></div></td>
      <td>${'· '.repeat(i.depth)}${esc(i.title)}</td>
      <td>$${i.monthly_usd}</td>
      <td><span class="pill ${i.status}">${i.status}</span></td>
    </tr>`).join('') || '<tr><td class="muted">nothing yet</td></tr>';

  document.getElementById('recent').innerHTML = d.recent.map(r=>`
    <tr class="clickable" onclick="openIdea(${r.idea_id})">
      <td class="muted">${esc(r.ago)}</td><td>${esc(r.title)}</td><td>${r.n}</td>
      <td><span class="pill ${r.verdict}">${r.verdict} ${r.score}</span></td>
    </tr>`).join('') || '<tr><td class="muted">no rounds yet</td></tr>';

  document.getElementById('lessons').innerHTML =
    d.lessons.map(l=>`<div style="margin-bottom:8px">— ${esc(l.text)}</div>`).join('')
    || 'none yet';

  document.getElementById('killed').innerHTML = d.killed.map(k=>`
    <tr><td class="KILL">✕</td><td>${esc(k.title)}</td><td class="muted">${k.best_score}</td></tr>`).join('')
    || '<tr><td class="muted">nothing killed yet</td></tr>';
}

async function toggle(id){ await fetch('/api/action/'+id+'/toggle',{method:'POST'}); poll(); }

async function openIdea(id){
  const d = await (await fetch('/api/idea/'+id)).json();
  if(d.error) return;
  let h = `<h2>${esc(d.idea.title)}</h2>
    <div class="muted">depth ${d.idea.depth} · ${esc(d.idea.status)} · best score ${d.idea.best_score}
    · est $${d.idea.monthly_usd}/mo · confidence ${esc(d.idea.confidence)}</div>`;
  if(d.idea.question) h += `<div class="role">SUB-QUESTION</div><pre>${esc(d.idea.question)}</pre>`;
  h += `<div class="role">THESIS</div><pre>${esc(d.idea.thesis)}</pre>`;
  d.rounds.forEach(r=>{
    h += `<h2 style="margin-top:26px">ROUND ${r.n} — ${r.verdict} @ ${r.score} <span class="muted">${esc(r.ago)}</span></h2>`;
    h += `<div class="role">▲ BULL</div><pre>${esc(r.bull)}</pre>`;
    h += `<div class="role">▼ BEAR</div><pre>${esc(r.bear)}</pre>`;
    h += `<div class="role">⚖ JUDGE</div><pre>${esc(r.judge.rationale||'')}

STRONGEST OBJECTION: ${esc(r.judge.strongest_objection||'')}
LESSON: ${esc(r.judge.lesson||'')}</pre>`;
  });
  document.getElementById('modalbody').innerHTML = h;
  document.getElementById('modal').style.display='block';
}

document.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('modal').style.display='none';});
setInterval(poll, 10000); poll();
</script>
</body>
</html>
HTMLEOF

echo "[7/7] Installing systemd services..."
if [ "${MA_SKIP_SYSTEMD:-0}" != "1" ]; then
sudo tee /etc/systemd/system/money-agent.service > /dev/null << EOF
[Unit]
Description=Money Agent - recursive two-agent debate engine
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/config.env
ExecStart=/usr/bin/python3 $APP_DIR/agent.py
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/money-agent-web.service > /dev/null << EOF
[Unit]
Description=Money Agent dashboard
After=network.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/config.env
ExecStart=/usr/bin/python3 $APP_DIR/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now money-agent-web
sudo systemctl enable --now money-agent

mkdir -p "$HOME/Desktop"
cat > "$HOME/Desktop/money-agent.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Money Agent
Comment=Recursive debate engine
Exec=chromium http://localhost:$PORT
Icon=applications-office
Terminal=false
EOF
chmod +x "$HOME/Desktop/money-agent.desktop"
gio set "$HOME/Desktop/money-agent.desktop" metadata::trusted true 2>/dev/null || true

sleep 3
echo ""
sudo systemctl status money-agent --no-pager | head -6
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "YOUR_PI_IP")
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   ✅ Money Agent Online                               ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║                                                      ║"
echo "║  Dashboard:  http://$IP:$PORT"
echo "║                                                      ║"
echo "║  1. Add your API key (else it uses the claude CLI,   ║"
echo "║     else dry-run):                                   ║"
echo "║       nano $APP_DIR/config.env"
echo "║  2. Tell it who it is earning for — this steers       ║"
echo "║     every idea it has:                                ║"
echo "║       nano $APP_DIR/profile.json"
echo "║  3. Restart:  sudo systemctl restart money-agent      ║"
echo "║                                                      ║"
echo "║  Watch it think:                                      ║"
echo "║     journalctl -u money-agent -f                     ║"
echo "║  Spend cap lives in config.env (MA_DAILY_USD).        ║"
echo "║                                                      ║"
echo "║  It finds and stress-tests plays. It does not spend,  ║"
echo "║  sell or collect — the ACTION QUEUE is your part.     ║"
echo "║                                                      ║"
echo "╚══════════════════════════════════════════════════════╝"
