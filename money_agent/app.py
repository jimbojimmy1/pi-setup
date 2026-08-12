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
