"""Dashboard for the money agent."""
import json
import os
from pathlib import Path
import time

from flask import Flask, jsonify, render_template, request

try:
    from . import store
except ImportError:  # Installed scripts also run directly on the Raspberry Pi.
    import store

app = Flask(__name__)
DAILY_USD = float(os.environ.get("MA_DAILY_USD", "2.00") or 0)
_ready = False

PUBLIC_EXPERIMENT_FIELDS = (
    "id",
    "idea_id",
    "project",
    "action_kind",
    "hypothesis",
    "deliverable",
    "metric",
    "measurement_source",
    "stop_condition",
    "window_days",
    "autonomy_class",
    "status",
    "result",
    "hours",
    "cost_usd",
    "created_at",
    "updated_at",
)
PUBLIC_OBSERVATION_FIELDS = (
    "id",
    "experiment_id",
    "source_kind",
    "metric",
    "value",
    "revenue_usd",
    "observed_at",
)


def _artifact_root():
    return Path(
        os.environ.get("MA_ARTIFACT_ROOT", Path(__file__).resolve().parent / "artifacts")
    ).resolve()


def _next_work():
    path = _artifact_root() / "next-work.json"
    try:
        if path.stat().st_size > 256_000:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _inbox_counts():
    inbox = _artifact_root() / "observation-inbox"
    counts = {}
    for name in ("incoming", "processing", "accepted", "rejected"):
        try:
            counts[name] = sum(
                1
                for entry in os.scandir(inbox / name)
                if entry.name.endswith(".json") and entry.is_file(follow_symlinks=False)
            )
        except OSError:
            counts[name] = 0
    return counts


def _latest_availability(observations):
    for item in observations:
        if (
            item["source_kind"] == "public_http"
            and item["metric"] == "public_availability"
        ):
            observed_at = float(item["observed_at"])
            return {
                "available": float(item["value"]) > 0,
                "observed_at": observed_at,
                "age": ago(observed_at),
            }
    return None


def _owner_blockers(experiments):
    blockers = [
        {
            "project": "FunnelSleuth",
            "action": "Connect the existing Stripe or PayPal checkout link.",
            "reason": "This requires an owner-authenticated payment account session.",
        }
    ]
    blockers.extend(
        {
            "project": item["project"],
            "action": item["deliverable"],
            "reason": "Policy classified this experiment as OWNER_REQUIRED.",
        }
        for item in experiments
        if item["autonomy_class"] == "OWNER_REQUIRED"
        and item["status"] not in ("won", "lost")
    )
    blockers.extend(
        {
            "project": item["project"],
            "action": "Configure a trustworthy read-only measurement source.",
            "reason": item["result"] or "Measurement is blocked.",
        }
        for item in experiments
        if item["status"] == "blocked"
    )
    return blockers


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
    experiments = [
        {key: item[key] for key in PUBLIC_EXPERIMENT_FIELDS}
        for item in store.list_experiments()
    ]
    observations = [
        {key: item[key] for key in PUBLIC_OBSERVATION_FIELDS}
        for item in store.list_observations()
    ]
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
            "experiments": experiments,
            "observations": observations,
            "inbox": _inbox_counts(),
            "availability": _latest_availability(observations),
            "next_work": _next_work(),
            "owner_blockers": _owner_blockers(experiments),
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
