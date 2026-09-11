"""Atomic local inbox for policy-checked observation evidence."""

from __future__ import annotations

import os
from pathlib import Path
import uuid

try:
    from . import store
    from .import_observation import (
        ImportError as ObservationImportError,
        MAX_INPUT_BYTES,
        parse_payload,
    )
    from .monitoring import MonitoringError, ingest_observation
except ImportError:  # Installed scripts also run directly on the Raspberry Pi.
    import store
    from import_observation import (
        ImportError as ObservationImportError,
        MAX_INPUT_BYTES,
        parse_payload,
    )
    from monitoring import MonitoringError, ingest_observation


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _archive(claimed: Path, destination: Path) -> None:
    target = destination / claimed.name
    os.replace(claimed, target)
    try:
        target.chmod(0o600)
    except OSError:
        pass


def _read_bounded(path: Path) -> str:
    with path.open("r", encoding="utf-8") as handle:
        return handle.read(MAX_INPUT_BYTES + 1)


def process_inbox(artifact_root: Path | str, limit: int = 25) -> dict:
    """Claim, validate, ingest, and archive bounded local observation files."""
    root = Path(artifact_root).resolve()
    inbox = root / "observation-inbox"
    incoming = inbox / "incoming"
    processing = inbox / "processing"
    accepted_dir = inbox / "accepted"
    rejected_dir = inbox / "rejected"
    for directory in (incoming, processing, accepted_dir, rejected_dir):
        _private_directory(directory)

    bounded_limit = max(0, min(int(limit), 100))
    candidates = sorted(incoming.glob("*.json"), key=lambda path: path.name)
    accepted = rejected = 0
    store.init()

    for source in candidates[:bounded_limit]:
        claimed = processing / f"{uuid.uuid4().hex}.json"
        try:
            os.replace(source, claimed)
        except OSError:
            continue
        try:
            if claimed.is_symlink() or not claimed.is_file():
                raise ObservationImportError("inbox entry must be a regular file")
            payload = parse_payload(_read_bounded(claimed))
            ingest_observation(
                experiment_id=payload["experiment_id"],
                source_kind=payload["source_kind"],
                metric=payload["metric"],
                value=payload["value"],
                evidence_ref=payload["evidence_ref"],
                observed_at=payload["observed_at"],
                revenue_usd=payload["revenue_usd"],
                outcome=payload["outcome"],
                window_complete=payload["window_complete"],
            )
            _archive(claimed, accepted_dir)
            accepted += 1
        except (ObservationImportError, MonitoringError, OSError, UnicodeError):
            try:
                _archive(claimed, rejected_dir)
            except OSError:
                pass
            rejected += 1

    remaining = sum(1 for _ in incoming.glob("*.json"))
    return {"accepted": accepted, "rejected": rejected, "remaining": remaining}
