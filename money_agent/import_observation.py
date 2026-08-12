"""Strict local JSON boundary for experiment observations."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
from typing import TextIO

try:
    from . import store
    from .monitoring import MonitoringError, ingest_observation
except ImportError:  # Installed scripts also run directly on the Raspberry Pi.
    import store
    from monitoring import MonitoringError, ingest_observation


MAX_INPUT_BYTES = 65_536
REQUIRED_FIELDS = {
    "experiment_id",
    "source_kind",
    "metric",
    "value",
    "evidence_ref",
    "observed_at",
}
OPTIONAL_FIELDS = {"revenue_usd", "outcome", "window_complete"}
ALLOWED_OUTCOMES = {None, "measuring", "won", "lost"}
SENSITIVE_KEY_FRAGMENTS = {
    "authorization",
    "cookie",
    "key",
    "password",
    "secret",
    "token",
}


class ImportError(ValueError):
    """Raised when a local observation payload is invalid."""


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _bounded_text(value, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ImportError(f"{field} must be non-empty text of at most {maximum} chars")
    if any(ord(character) < 32 for character in value):
        raise ImportError(f"{field} cannot contain control characters")
    return value.strip()


def parse_payload(text: str) -> dict:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ImportError("observation input is too large")
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ImportError("observation input must be one JSON object") from exc
    if not isinstance(payload, dict):
        raise ImportError("observation input must be one JSON object")
    for key in payload:
        normalized = str(key).lower()
        if any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS):
            raise ImportError("observation payload contains a sensitive field")
    allowed = REQUIRED_FIELDS | OPTIONAL_FIELDS
    if set(payload) - allowed:
        raise ImportError("observation payload contains unknown fields")
    if REQUIRED_FIELDS - set(payload):
        raise ImportError("observation payload is missing required fields")

    experiment_id = payload["experiment_id"]
    if not isinstance(experiment_id, int) or isinstance(experiment_id, bool):
        raise ImportError("experiment_id must be an integer")
    if experiment_id < 1:
        raise ImportError("experiment_id must be positive")
    source_kind = _bounded_text(payload["source_kind"], "source_kind", 64)
    metric = _bounded_text(payload["metric"], "metric", 500)
    evidence_ref = _bounded_text(payload["evidence_ref"], "evidence_ref", 512)

    value = payload["value"]
    observed_at = payload["observed_at"]
    revenue_usd = payload.get("revenue_usd", 0)
    if not all(_is_number(item) and math.isfinite(float(item)) for item in (
        value,
        observed_at,
        revenue_usd,
    )):
        raise ImportError("value, observed_at, and revenue_usd must be finite numbers")
    if float(observed_at) <= 0:
        raise ImportError("observed_at must be positive")
    if float(revenue_usd) < 0:
        raise ImportError("revenue_usd cannot be negative")

    outcome = payload.get("outcome")
    if outcome not in ALLOWED_OUTCOMES:
        raise ImportError("outcome must be measuring, won, lost, or null")
    window_complete = payload.get("window_complete", False)
    if not isinstance(window_complete, bool):
        raise ImportError("window_complete must be boolean")

    return {
        "experiment_id": experiment_id,
        "source_kind": source_kind,
        "metric": metric,
        "value": float(value),
        "evidence_ref": evidence_ref,
        "observed_at": float(observed_at),
        "revenue_usd": float(revenue_usd),
        "outcome": outcome,
        "window_complete": window_complete,
    }


def _read_source(source: str, input_stream: TextIO) -> str:
    if source == "-":
        return input_stream.read(MAX_INPUT_BYTES + 1)
    path = Path(source)
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ImportError("observation input is too large")
    return path.read_text(encoding="utf-8")


def main(
    argv=None,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    error_stream: TextIO | None = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    input_stream = sys.stdin if input_stream is None else input_stream
    output_stream = sys.stdout if output_stream is None else output_stream
    error_stream = sys.stderr if error_stream is None else error_stream
    if len(args) != 1:
        error_stream.write("usage: import_observation.py FILE|-\n")
        return 2
    try:
        payload = parse_payload(_read_source(args[0], input_stream))
        if payload["outcome"] is not None or payload["window_complete"]:
            raise ImportError("terminal outcome import is not enabled")
        store.init()
        observation = ingest_observation(
            experiment_id=payload["experiment_id"],
            source_kind=payload["source_kind"],
            metric=payload["metric"],
            value=payload["value"],
            evidence_ref=payload["evidence_ref"],
            observed_at=payload["observed_at"],
            revenue_usd=payload["revenue_usd"],
        )
        experiment = store.get_experiment(payload["experiment_id"])
    except (ImportError, MonitoringError, OSError, UnicodeError):
        error_stream.write("error: observation import rejected\n")
        return 2
    output_stream.write(
        json.dumps(
            {
                "experiment_id": payload["experiment_id"],
                "observation_id": observation["id"],
                "status": experiment["status"],
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
