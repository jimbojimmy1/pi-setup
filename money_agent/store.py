"""SQLite store. Two processes (daemon + web) share it, so WAL + busy_timeout."""
import json
import math
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
CREATE TABLE IF NOT EXISTS experiments(
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id        INTEGER NOT NULL,
  project        TEXT    NOT NULL,
  action_kind    TEXT    NOT NULL,
  hypothesis     TEXT    NOT NULL,
  deliverable    TEXT    NOT NULL,
  metric         TEXT    NOT NULL,
  measurement_source TEXT NOT NULL DEFAULT '',
  stop_condition TEXT    NOT NULL DEFAULT '',
  window_days    INTEGER NOT NULL,
  autonomy_class TEXT    NOT NULL,
  status         TEXT    NOT NULL DEFAULT 'ready',
  hours          REAL    NOT NULL DEFAULT 0,
  cost_usd       REAL    NOT NULL DEFAULT 0,
  artifact_path  TEXT    NOT NULL DEFAULT '',
  result         TEXT    NOT NULL DEFAULT '',
  lease_until    REAL    NOT NULL DEFAULT 0,
  created_at     REAL    NOT NULL,
  updated_at     REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS experiment_events(
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id INTEGER NOT NULL,
  event_type    TEXT    NOT NULL,
  detail        TEXT    NOT NULL DEFAULT '',
  created_at    REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS observations(
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id INTEGER NOT NULL,
  source_kind   TEXT    NOT NULL,
  metric        TEXT    NOT NULL,
  value         REAL    NOT NULL,
  revenue_usd   REAL    NOT NULL DEFAULT 0,
  evidence_ref  TEXT    NOT NULL,
  observed_at   REAL    NOT NULL,
  created_at    REAL    NOT NULL,
  UNIQUE(experiment_id, source_kind, evidence_ref)
);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_rounds_idea ON rounds(idea_id);
CREATE INDEX IF NOT EXISTS idx_actions_idea ON actions(idea_id);
CREATE INDEX IF NOT EXISTS idx_usage_day ON usage(day);
CREATE INDEX IF NOT EXISTS idx_experiments_status
  ON experiments(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_experiment_events_experiment
  ON experiment_events(experiment_id, id);
CREATE INDEX IF NOT EXISTS idx_observations_experiment
  ON observations(experiment_id, observed_at, id);
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
    columns = {
        row["name"] for row in c.execute("PRAGMA table_info(experiments)").fetchall()
    }
    if "stop_condition" not in columns:
        c.execute(
            "ALTER TABLE experiments ADD COLUMN stop_condition TEXT NOT NULL DEFAULT ''"
        )
    if "measurement_source" not in columns:
        c.execute(
            "ALTER TABLE experiments ADD COLUMN measurement_source TEXT NOT NULL"
            " DEFAULT ''"
        )
    c.commit()


def close_connection():
    c = getattr(_local, "c", None)
    if c is not None:
        c.close()
        _local.c = None


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


def claim_target(max_rounds):
    """Atomically claim the idea most deserving of the next debate round.

    Shallow before deep (bank the fundamentals first), fewest rounds first
    (don't starve anything), then most promising. The claim flips it to
    'working' inside an IMMEDIATE transaction so parallel workers — or a second
    daemon someone forgot about — can never grab the same idea twice.
    """
    c = conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        r = c.execute(
            "SELECT * FROM ideas WHERE status IN ('pending','live') AND rounds < ?"
            " ORDER BY depth ASC, rounds ASC, best_score DESC, id ASC LIMIT 1",
            (max_rounds,),
        ).fetchone()
        if r is None:
            c.execute("COMMIT")
            return None
        c.execute(
            "UPDATE ideas SET status='working', updated_at=? WHERE id=?",
            (time.time(), r["id"]),
        )
        c.execute("COMMIT")
        return dict(r)
    except Exception:
        c.execute("ROLLBACK")
        raise


def release(idea_id, had_rounds):
    """Hand a claimed idea back unworked (crash, LLM error, shutdown)."""
    conn().execute(
        "UPDATE ideas SET status=?, updated_at=? WHERE id=? AND status='working'",
        ("live" if had_rounds else "pending", time.time(), idea_id),
    )
    conn().commit()


def release_stale():
    """Startup recovery: anything left 'working' by a killed process."""
    c = conn()
    cur = c.execute(
        "UPDATE ideas SET status = CASE WHEN rounds > 0 THEN 'live' ELSE 'pending' END"
        " WHERE status='working'"
    )
    c.commit()
    return cur.rowcount


def open_count():
    return conn().execute(
        "SELECT COUNT(*) n FROM ideas WHERE status IN ('pending','live','working')"
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


# ---------- experiments ----------
def add_experiment(
    idea_id,
    project,
    action_kind,
    hypothesis,
    deliverable,
    metric,
    stop_condition,
    window_days,
    autonomy_class,
    hours,
    cost_usd,
    measurement_source="",
):
    now = time.time()
    c = conn()
    cur = c.execute(
        "INSERT INTO experiments(idea_id,project,action_kind,hypothesis,deliverable,"
        "metric,measurement_source,stop_condition,window_days,autonomy_class,status,"
        "hours,cost_usd,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,'ready',?,?,?,?)",
        (
            int(idea_id),
            str(project).strip(),
            str(action_kind).strip(),
            str(hypothesis).strip(),
            str(deliverable).strip(),
            str(metric).strip(),
            str(measurement_source).strip(),
            str(stop_condition).strip(),
            int(window_days),
            str(autonomy_class).strip(),
            float(hours or 0),
            float(cost_usd or 0),
            now,
            now,
        ),
    )
    c.commit()
    return cur.lastrowid


def find_experiment(idea_id, project, action_kind, deliverable):
    row = conn().execute(
        "SELECT * FROM experiments WHERE idea_id=? AND project=? AND action_kind=?"
        " AND deliverable=? ORDER BY id ASC LIMIT 1",
        (
            int(idea_id),
            str(project).strip(),
            str(action_kind).strip(),
            str(deliverable).strip(),
        ),
    ).fetchone()
    return dict(row) if row else None


def get_experiment(experiment_id):
    row = conn().execute(
        "SELECT * FROM experiments WHERE id=?", (experiment_id,)
    ).fetchone()
    return dict(row) if row else None


def list_experiments(limit=50):
    if limit is None:
        rows = conn().execute(
            "SELECT * FROM experiments ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    else:
        if type(limit) is not int or limit < 1:
            raise ValueError("experiment limit must be a positive integer or None")
        rows = conn().execute(
            "SELECT * FROM experiments ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def claim_experiment(lease_seconds=900):
    c = conn()
    now = time.time()
    c.execute("BEGIN IMMEDIATE")
    try:
        row = c.execute(
            "SELECT id FROM experiments WHERE status='ready'"
            " ORDER BY updated_at ASC, id ASC LIMIT 1"
        ).fetchone()
        if row is None:
            c.execute("COMMIT")
            return None
        lease_until = now + float(lease_seconds)
        c.execute(
            "UPDATE experiments SET status='exported', lease_until=?, updated_at=?"
            " WHERE id=?",
            (lease_until, now, row["id"]),
        )
        claimed = c.execute(
            "SELECT * FROM experiments WHERE id=?", (row["id"],)
        ).fetchone()
        c.execute("COMMIT")
        return dict(claimed)
    except Exception:
        c.execute("ROLLBACK")
        raise


def recover_stale_experiments():
    c = conn()
    cur = c.execute(
        "UPDATE experiments SET status='ready', lease_until=0, updated_at=?"
        " WHERE status='exported' AND lease_until < ?",
        (time.time(), time.time()),
    )
    c.commit()
    return cur.rowcount


def add_experiment_event(experiment_id, event_type, detail=""):
    c = conn()
    cur = c.execute(
        "INSERT INTO experiment_events(experiment_id,event_type,detail,created_at)"
        " VALUES(?,?,?,?)",
        (int(experiment_id), str(event_type), str(detail), time.time()),
    )
    c.commit()
    return cur.lastrowid


def experiment_events(experiment_id):
    rows = conn().execute(
        "SELECT * FROM experiment_events WHERE experiment_id=? ORDER BY id ASC",
        (int(experiment_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def update_experiment_status(experiment_id, status, result=None):
    c = conn()
    now = time.time()
    if result is None:
        c.execute(
            "UPDATE experiments SET status=?, updated_at=? WHERE id=?",
            (str(status), now, int(experiment_id)),
        )
    else:
        c.execute(
            "UPDATE experiments SET status=?, result=?, updated_at=? WHERE id=?",
            (str(status), str(result), now, int(experiment_id)),
        )
    c.commit()


# ---------- observations ----------
def add_observation(
    experiment_id,
    source_kind,
    metric,
    value,
    revenue_usd,
    evidence_ref,
    observed_at,
):
    c = conn()
    now = time.time()
    values = (
        int(experiment_id),
        str(source_kind).strip(),
        str(metric).strip(),
        float(value),
        float(revenue_usd or 0),
        str(evidence_ref).strip(),
        float(observed_at),
        now,
    )
    c.execute(
        "INSERT OR IGNORE INTO observations("
        "experiment_id,source_kind,metric,value,revenue_usd,evidence_ref,"
        "observed_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
        values,
    )
    row = c.execute(
        "SELECT id FROM observations WHERE experiment_id=? AND source_kind=?"
        " AND evidence_ref=?",
        (values[0], values[1], values[5]),
    ).fetchone()
    c.commit()
    return row["id"]


def list_observations(experiment_id=None, limit=100):
    if experiment_id is None:
        rows = conn().execute(
            "SELECT * FROM observations ORDER BY observed_at DESC, id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    else:
        rows = conn().execute(
            "SELECT * FROM observations WHERE experiment_id=?"
            " ORDER BY observed_at DESC, id DESC LIMIT ?",
            (int(experiment_id), int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def verified_revenue_summary():
    rows = conn().execute(
        "SELECT source_kind, evidence_ref, revenue_usd, observed_at"
        " FROM observations"
        " WHERE source_kind IN (?, ?)"
        " AND typeof(revenue_usd) IN ('integer', 'real') AND revenue_usd > 0"
        " AND typeof(observed_at) IN ('integer', 'real') AND observed_at > 0"
        " AND typeof(evidence_ref) = 'text'"
        " AND length(trim(evidence_ref)) BETWEEN 1 AND 512",
        ("payment_provider_readonly", "owner_verified"),
    )
    deduplicated = {}
    for row in rows:
        amount = float(row["revenue_usd"])
        observed_at = float(row["observed_at"])
        if not math.isfinite(amount) or not math.isfinite(observed_at):
            continue
        key = (row["source_kind"], row["evidence_ref"])
        existing = deduplicated.get(key)
        if existing is None:
            deduplicated[key] = (amount, observed_at)
        else:
            deduplicated[key] = (
                min(existing[0], amount),
                max(existing[1], observed_at),
            )

    total = 0.0
    payments = 0
    last_observed_at = None
    for amount, observed_at in deduplicated.values():
        next_total = total + amount
        if not math.isfinite(next_total):
            continue
        total = next_total
        payments += 1
        if last_observed_at is None or observed_at > last_observed_at:
            last_observed_at = observed_at
    return {
        "total_usd": total,
        "payments": payments,
        "last_observed_at": last_observed_at,
    }


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
        " WHERE a.done=0 AND i.status IN ('promoted','live','pending','parked','working')"
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
