"""Fail-closed measurement policy for revenue experiments."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
import ssl
import time
from urllib.parse import urlsplit, urlunsplit

try:
    from . import store
except ImportError:  # Installed scripts also run directly on the Raspberry Pi.
    import store


ALLOWED_SOURCES = {
    "analytics_readonly",
    "owner_verified",
    "payment_provider_readonly",
    "public_http",
}
REVENUE_SOURCES = {"owner_verified", "payment_provider_readonly"}
TERMINAL_STATUSES = {"won", "lost"}


class MonitoringError(ValueError):
    """Raised when evidence cannot cross the monitoring boundary."""


def _require_global_address(value: str) -> None:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError as exc:
        raise MonitoringError("monitor target did not resolve to an IP address") from exc
    if not address.is_global:
        raise MonitoringError("monitor target must resolve only to public addresses")


def _validated_https_target(url: str, resolver=socket.getaddrinfo) -> dict:
    raw_url = str(url).strip()
    if any(ord(character) < 32 for character in raw_url):
        raise MonitoringError("monitor URL cannot contain control characters")
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except ValueError as exc:
        raise MonitoringError("invalid monitor URL") from exc
    if parsed.scheme.lower() != "https":
        raise MonitoringError("monitor URL must use HTTPS")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise MonitoringError("monitor URL must have a host and no credentials")
    if port not in (None, 443):
        raise MonitoringError("monitor URL must use the default HTTPS port")

    host = parsed.hostname
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        addresses = [host]
    except ValueError:
        try:
            answers = resolver(host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise MonitoringError("monitor target could not be resolved") from exc
        addresses = [answer[4][0] for answer in answers]
    if not addresses:
        raise MonitoringError("monitor target returned no addresses")
    for address in addresses:
        _require_global_address(address)

    netloc = parsed.hostname.lower()
    if ":" in netloc:
        netloc = f"[{netloc}]"
    normalized = urlunsplit(("https", netloc, parsed.path or "", parsed.query, ""))
    request_target = parsed.path or "/"
    if parsed.query:
        request_target += f"?{parsed.query}"
    try:
        request_target.encode("ascii")
    except UnicodeEncodeError as exc:
        raise MonitoringError("monitor URL path must be ASCII or percent-encoded") from exc
    return {
        "url": normalized,
        "host": parsed.hostname.lower(),
        "addresses": addresses,
        "path": request_target,
    }


def validate_public_https_url(url: str, resolver=socket.getaddrinfo) -> str:
    """Validate a bounded public HTTPS target and return its normalized URL."""
    return _validated_https_target(url, resolver=resolver)["url"]


def _tls_head(host, address, path, timeout, max_response_bytes):
    request = (
        f"HEAD {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "User-Agent: money-agent-health/1\r\n"
        "Accept: */*\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    context = ssl.create_default_context()
    with socket.create_connection((address, 443), timeout=float(timeout)) as raw:
        with context.wrap_socket(raw, server_hostname=host) as secured:
            secured.settimeout(float(timeout))
            secured.sendall(request)
            response = bytearray()
            while len(response) < int(max_response_bytes) and b"\r\n" not in response:
                chunk = secured.recv(min(1024, int(max_response_bytes) - len(response)))
                if not chunk:
                    break
                response.extend(chunk)
    status_line = bytes(response).split(b"\r\n", 1)[0]
    parts = status_line.split(b" ", 2)
    if len(parts) < 2 or not parts[0].startswith(b"HTTP/"):
        raise MonitoringError("monitor target returned an invalid HTTP response")
    try:
        status = int(parts[1])
    except ValueError as exc:
        raise MonitoringError("monitor target returned an invalid HTTP status") from exc
    if status < 100 or status > 599:
        raise MonitoringError("monitor target returned an invalid HTTP status")
    return status


def probe_public_https(
    url: str,
    *,
    resolver=socket.getaddrinfo,
    connector=_tls_head,
    timeout=10,
    max_response_bytes=4096,
) -> dict:
    """Make one direct-IP HTTPS HEAD request without following redirects."""
    target = _validated_https_target(url, resolver=resolver)
    try:
        status = connector(
            target["host"],
            target["addresses"][0],
            target["path"],
            max(1, min(float(timeout), 30)),
            max(256, min(int(max_response_bytes), 16_384)),
        )
    except (OSError, ssl.SSLError, MonitoringError):
        status = 0
    return {
        "url": target["url"],
        "status": int(status),
        "available": 200 <= int(status) < 400,
    }


def collect_public_health(
    experiment_id: int,
    *,
    now: float | None = None,
    bucket_seconds=3600,
    resolver=socket.getaddrinfo,
    connector=_tls_head,
) -> dict:
    """Record at most one availability-only observation per time bucket."""
    experiment = store.get_experiment(experiment_id)
    if experiment is None:
        raise MonitoringError("experiment does not exist")
    source = str(experiment.get("measurement_source") or "").strip()
    if configured_source_kind(source) != "public_http":
        raise MonitoringError("experiment does not use a public health source")
    if experiment["metric"].strip() != "public_availability":
        raise MonitoringError("public health experiments must use public_availability")

    target_url = source.removeprefix("public_http:")
    normalized = validate_public_https_url(target_url, resolver=resolver)
    observed_at = float(time.time() if now is None else now)
    interval = max(60, min(int(bucket_seconds), 86_400))
    bucket = int(observed_at // interval)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
    evidence_ref = f"public-health:{digest}:{bucket}"
    existing = next(
        (
            observation
            for observation in store.list_observations(experiment_id)
            if observation["source_kind"] == "public_http"
            and observation["evidence_ref"] == evidence_ref
        ),
        None,
    )
    if existing is not None:
        return existing

    probe = probe_public_https(
        target_url,
        resolver=resolver,
        connector=connector,
    )
    return ingest_observation(
        experiment_id=experiment_id,
        source_kind="public_http",
        metric="public_availability",
        value=1 if probe["available"] else 0,
        revenue_usd=0,
        evidence_ref=evidence_ref,
        observed_at=observed_at,
        outcome=None,
        window_complete=False,
    )


def configured_source_kind(measurement_source: str) -> str:
    source = str(measurement_source or "").strip()
    if source.startswith("public_http:"):
        return "public_http"
    return source


def _add_event_once(experiment_id: int, event_type: str, detail: str) -> None:
    if any(
        event["event_type"] == event_type and event["detail"] == detail
        for event in store.experiment_events(experiment_id)
    ):
        return
    store.add_experiment_event(experiment_id, event_type, detail)


def monitor_experiment(experiment_id: int) -> dict:
    """Validate measurement readiness; block missing or unsafe sources."""
    experiment = store.get_experiment(experiment_id)
    if experiment is None:
        raise MonitoringError("experiment does not exist")
    source = str(experiment.get("measurement_source") or "").strip()
    source_kind = configured_source_kind(source)
    detail = "A trustworthy measurement source is not configured."

    try:
        if source_kind not in ALLOWED_SOURCES:
            raise MonitoringError(detail)
        if source_kind == "public_http":
            target = source.removeprefix("public_http:")
            validate_public_https_url(target)
    except MonitoringError as exc:
        detail = str(exc)
        if experiment["status"] not in TERMINAL_STATUSES:
            store.update_experiment_status(experiment_id, "blocked", result=detail)
            _add_event_once(experiment_id, "blocked", detail)
        return store.get_experiment(experiment_id)

    return experiment


def ingest_observation(
    experiment_id: int,
    source_kind: str,
    metric: str,
    value: float,
    evidence_ref: str,
    observed_at: float | None = None,
    revenue_usd: float = 0,
    outcome: str | None = None,
    window_complete: bool = False,
) -> dict:
    """Record explicit evidence without inferring sales from unrelated metrics."""
    experiment = store.get_experiment(experiment_id)
    if experiment is None:
        raise MonitoringError("experiment does not exist")
    source_kind = str(source_kind).strip()
    expected_source = configured_source_kind(experiment["measurement_source"])
    if source_kind not in ALLOWED_SOURCES or source_kind != expected_source:
        raise MonitoringError("evidence source is unknown or does not match the experiment")
    if str(metric).strip() != experiment["metric"].strip():
        raise MonitoringError("evidence metric does not match the experiment")
    evidence_ref = str(evidence_ref).strip()
    if not evidence_ref:
        raise MonitoringError("evidence reference is required")
    try:
        numeric_value = float(value)
        numeric_revenue = float(revenue_usd or 0)
        observed = float(time.time() if observed_at is None else observed_at)
    except (TypeError, ValueError) as exc:
        raise MonitoringError("evidence values must be numeric") from exc
    if numeric_revenue < 0:
        raise MonitoringError("observed revenue cannot be negative")
    if numeric_revenue > 0 and source_kind not in REVENUE_SOURCES:
        raise MonitoringError("revenue requires payment-provider or owner evidence")
    if source_kind == "public_http" and numeric_revenue != 0:
        raise MonitoringError("public health evidence cannot report revenue")
    if outcome not in (None, "measuring", "won", "lost"):
        raise MonitoringError("outcome must be measuring, won, lost, or null")
    if not isinstance(window_complete, bool):
        raise MonitoringError("window_complete must be boolean")
    target_status = outcome if outcome in TERMINAL_STATUSES else "measuring"
    if target_status in TERMINAL_STATUSES and source_kind == "public_http":
        raise MonitoringError("public health evidence cannot close an experiment")
    if target_status == "won" and numeric_value <= 0 and numeric_revenue <= 0:
        raise MonitoringError("won requires a positive verified metric or payment")
    if target_status == "lost":
        if not window_complete:
            raise MonitoringError("lost requires a completed measurement window")
        if numeric_revenue > 0:
            raise MonitoringError("an experiment with an observed payment cannot be lost")
    elif window_complete:
        raise MonitoringError("window_complete is valid only with a lost outcome")

    current_status = experiment["status"]
    if (
        current_status in TERMINAL_STATUSES
        and target_status in TERMINAL_STATUSES
        and target_status != current_status
    ):
        raise MonitoringError("terminal experiment outcomes cannot conflict")

    existing = next(
        (
            observation
            for observation in store.list_observations(experiment_id)
            if observation["source_kind"] == source_kind
            and observation["evidence_ref"] == evidence_ref
        ),
        None,
    )
    if existing is not None:
        return existing

    observation_id = store.add_observation(
        experiment_id=experiment_id,
        source_kind=source_kind,
        metric=metric,
        value=numeric_value,
        revenue_usd=numeric_revenue,
        evidence_ref=evidence_ref,
        observed_at=observed,
    )
    detail = f"Verified {metric}: {numeric_value:g} from {source_kind}."
    if numeric_revenue > 0:
        detail += f" Observed payment amount: ${numeric_revenue:.2f}."
    if current_status not in TERMINAL_STATUSES:
        store.update_experiment_status(experiment_id, target_status, result=detail)
    store.add_experiment_event(experiment_id, "observation", detail)
    if target_status in TERMINAL_STATUSES and current_status != target_status:
        store.add_experiment_event(experiment_id, target_status, detail)
        if target_status == "won":
            lesson = (
                f"Verified experiment win for {experiment['project']}: "
                f"{metric} reached {numeric_value:g}; preserve the tested "
                "mechanism before changing it."
            )
        else:
            lesson = (
                f"Completed experiment loss for {experiment['project']}: "
                f"{metric} ended at {numeric_value:g}; do not repeat the same "
                "hypothesis without new evidence."
            )
        store.add_lesson(experiment["idea_id"], experiment["project"], lesson)
    return next(
        observation
        for observation in store.list_observations(experiment_id)
        if observation["id"] == observation_id
    )
