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
