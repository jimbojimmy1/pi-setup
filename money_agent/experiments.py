"""Policy checks and durable exports for Money Agent experiments."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping


AUTO_LOCAL_ACTIONS = {
    "analyze_public_data",
    "public_health_check",
    "write_brief",
}
CODEX_REVIEWED_ACTIONS = {
    "build_owned_asset",
    "draft_pull_request",
    "edit_owned_site",
}
OWNER_REQUIRED_ACTIONS = {
    "change_payment",
    "create_account",
    "send_outreach",
    "spend_money",
}
REJECTED_ACTIONS = {
    "credential_harvest",
    "evade_terms",
    "fake_review",
    "spam",
}

REDACTED_KEY_FRAGMENTS = {
    "authorization",
    "cookie",
    "key",
    "password",
    "secret",
    "token",
}


@dataclass(frozen=True)
class ExportPaths:
    json_path: Path
    markdown_path: Path


def classify_action(action_kind: str, cost_usd: float = 0) -> str:
    """Return the least-permissive matching autonomy class."""
    if cost_usd > 0:
        return "OWNER_REQUIRED"
    if action_kind in REJECTED_ACTIONS:
        return "REJECTED"
    if action_kind in AUTO_LOCAL_ACTIONS:
        return "AUTO_LOCAL"
    if action_kind in CODEX_REVIEWED_ACTIONS:
        return "CODEX_REVIEWED"
    if action_kind in OWNER_REQUIRED_ACTIONS:
        return "OWNER_REQUIRED"
    return "OWNER_REQUIRED"


def _contains_sensitive_fragment(key: object) -> bool:
    normalized = str(key).lower()
    return any(fragment in normalized for fragment in REDACTED_KEY_FRAGMENTS)


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _redact(item)
            for key, item in value.items()
            if not _contains_sensitive_fragment(key)
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


def _markdown_handoff(payload: Mapping[str, Any]) -> str:
    fields = (
        ("Project", payload.get("project", "Unspecified")),
        ("Experiment", payload.get("experiment_id", "Unspecified")),
        ("Autonomy", payload.get("autonomy_class", "OWNER_REQUIRED")),
        ("Hypothesis", payload.get("hypothesis", "Unspecified")),
        ("Deliverable", payload.get("deliverable", "Unspecified")),
        ("Metric", payload.get("metric", "Unspecified")),
        ("Next action", payload.get("next_action", "Review the JSON work package.")),
    )
    lines = ["# Money Agent handoff", ""]
    lines.extend(f"- {label}: {value}" for label, value in fields)
    lines.extend(
        [
            "",
            "This handoff contains no credentials. Unknown or paid actions require owner approval.",
            "",
        ]
    )
    return "\n".join(lines)


def export_work_package(payload: Mapping[str, Any], artifact_root: Path | str) -> ExportPaths:
    """Atomically export a redacted work package inside ``artifact_root``."""
    root = Path(artifact_root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    json_path = root / "next-work.json"
    markdown_path = root / "HANDOFF.md"
    json_temp = root / ".next-work.json.tmp"
    markdown_temp = root / ".HANDOFF.md.tmp"
    sanitized = _redact(payload)

    try:
        json_temp.write_text(
            json.dumps(sanitized, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        markdown_temp.write_text(_markdown_handoff(sanitized), encoding="utf-8")
        os.replace(json_temp, json_path)
        os.replace(markdown_temp, markdown_path)
    finally:
        json_temp.unlink(missing_ok=True)
        markdown_temp.unlink(missing_ok=True)

    return ExportPaths(json_path=json_path, markdown_path=markdown_path)
