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
            # The CLI sometimes exits non-zero with nothing on stderr (transient
            # capacity being the usual cause), so surface the code and any
            # stdout too — an empty "CLI failed:" tells an operator nothing.
            detail = p.stderr.strip() or p.stdout.strip() or "no output"
            raise LLMError(f"claude CLI exit {p.returncode}: {detail[:300]}")
        if not p.stdout.strip():
            raise LLMError("claude CLI returned an empty response")
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
                "experiment": {},
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
