"""Validate the official/issuer source registry against the enabled poll list.

The registry is the auditable master catalog: access evidence for official and
issuer endpoints, including endpoints that are blocked or cannot provide a
verifiable publication timestamp. Only an ACTIVE endpoint may map to an enabled
collector source.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent
SCHEMA = "market-news-source-registry/1.0"
ACCESS_STATUSES = {"ACTIVE", "REGISTRY_ONLY", "BLOCKED", "NOT_FOUND", "UNREACHABLE"}
OFFICIAL_AUTHORITIES = {"official", "issuer"}


def load(path: Path | None = None) -> dict:
    target = path or ROOT / "source_registry.json"
    return json.loads(target.read_text(encoding="utf-8"))


def _normalized_url(value: str) -> str:
    parts = urlsplit(value.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _is_https(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme == "https" and bool(parts.netloc)


def flatten(registry: dict) -> list[dict]:
    rows = []
    for organization in registry.get("organizations", []):
        for endpoint in organization.get("endpoints", []):
            rows.append({**endpoint, "organization_id": organization.get("id", ""),
                         "organization_name": organization.get("name", "")})
    return rows


def validate(registry: dict, poll_sources: list[dict], *, require_all_official: bool = True,
             now: datetime | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(registry, dict):
        return ["Registry must be a JSON object"]
    if registry.get("schema") != SCHEMA:
        errors.append(f"Registry schema must be {SCHEMA}")
    organizations = registry.get("organizations")
    if not isinstance(organizations, list) or not organizations:
        return errors + ["Registry organizations must be a non-empty list"]

    seen_organizations: set[str] = set()
    seen_endpoints: set[str] = set()
    seen_poll_sources: set[str] = set()
    enabled_by_name = {str(source.get("name", "")): source
                       for source in poll_sources if source.get("enabled", True)}
    enabled_by_url = {_normalized_url(str(source.get("url", ""))): source
                      for source in poll_sources if source.get("enabled", True)}
    registered_poll_names: set[str] = set()

    for organization in organizations:
        org_id = organization.get("id")
        if not isinstance(org_id, str) or not org_id.strip():
            errors.append("Organization id is required")
        elif org_id in seen_organizations:
            errors.append(f"Duplicate organization id: {org_id}")
        else:
            seen_organizations.add(org_id)
        if not isinstance(organization.get("name"), str) or not organization["name"].strip():
            errors.append(f"Organization {org_id!r} needs a name")
        homepage = organization.get("homepage", "")
        if homepage and not _is_https(homepage):
            errors.append(f"Organization {org_id!r} homepage must be HTTPS")
        endpoints = organization.get("endpoints")
        if not isinstance(endpoints, list) or not endpoints:
            errors.append(f"Organization {org_id!r} needs endpoints")
            continue

        for endpoint in endpoints:
            endpoint_id = endpoint.get("id")
            label = f"{org_id}/{endpoint_id}"
            if not isinstance(endpoint_id, str) or not endpoint_id.strip():
                errors.append(f"{label}: endpoint id is required")
                continue
            if endpoint_id in seen_endpoints:
                errors.append(f"{label}: duplicate endpoint id")
            seen_endpoints.add(endpoint_id)
            if not isinstance(endpoint.get("name"), str) or not endpoint["name"].strip():
                errors.append(f"{label}: name is required")
            url = endpoint.get("url", "")
            if not _is_https(url):
                errors.append(f"{label}: URL must be HTTPS")
            status = endpoint.get("access_status")
            if status not in ACCESS_STATUSES:
                errors.append(f"{label}: invalid access_status {status!r}")
                continue
            evidence = endpoint.get("evidence")
            if not isinstance(evidence, dict):
                errors.append(f"{label}: evidence object is required")
                evidence = {}
            for field in ("checked_at", "method", "last_status"):
                if not isinstance(evidence.get(field), str) or not evidence[field].strip():
                    errors.append(f"{label}: evidence.{field} is required")
            try:
                datetime.fromisoformat(evidence.get("checked_at", ""))
            except (TypeError, ValueError):
                errors.append(f"{label}: evidence.checked_at must be ISO 8601")
            items = evidence.get("items")
            if not isinstance(items, int) or items < 0:
                errors.append(f"{label}: evidence.items must be a non-negative integer")
            http_status = evidence.get("http_status")
            if http_status is not None and (not isinstance(http_status, int)
                                            or not 100 <= http_status <= 599):
                errors.append(f"{label}: evidence.http_status is invalid")
            if status != "ACTIVE" and not str(endpoint.get("reason", "")).strip():
                errors.append(f"{label}: non-active endpoints need a reason")

            poll_source = endpoint.get("poll_source")
            if status == "ACTIVE":
                if not isinstance(poll_source, str) or not poll_source.strip():
                    errors.append(f"{label}: ACTIVE endpoint needs poll_source")
                    continue
                if poll_source in seen_poll_sources:
                    errors.append(f"{label}: duplicate poll_source {poll_source!r}")
                seen_poll_sources.add(poll_source)
                registered_poll_names.add(poll_source)
                source = enabled_by_name.get(poll_source)
                if source is None:
                    errors.append(f"{label}: poll_source {poll_source!r} is not enabled in sources.json")
                    continue
                if _normalized_url(str(source.get("url", ""))) != _normalized_url(url):
                    errors.append(f"{label}: poll_source URL does not match registry URL")
                if evidence.get("last_status") != "OK":
                    errors.append(f"{label}: ACTIVE endpoint needs last_status OK")
                if not isinstance(items, int) or items < 1:
                    errors.append(f"{label}: ACTIVE endpoint needs at least one parsed item")
            else:
                if poll_source not in (None, ""):
                    errors.append(f"{label}: non-active endpoint cannot have poll_source")
                enabled = enabled_by_name.get(str(endpoint.get("name", "")))
                if enabled is not None or _normalized_url(url) in enabled_by_url:
                    errors.append(f"{label}: non-active endpoint is enabled in sources.json")

    if require_all_official:
        for source in poll_sources:
            if not source.get("enabled", True):
                continue
            if source.get("authority") not in OFFICIAL_AUTHORITIES:
                continue
            name = str(source.get("name", ""))
            if name not in registered_poll_names:
                errors.append(f"Enabled official source {name!r} is missing from the registry")
    return errors


def summary(registry: dict) -> dict:
    rows = flatten(registry)
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("access_status", "UNKNOWN"))
        counts[status] = counts.get(status, 0) + 1
    return {"schema": registry.get("schema"), "organizations": len(registry.get("organizations", [])),
            "endpoints": len(rows), "by_status": dict(sorted(counts.items())),
            "active_poll_sources": sum(1 for row in rows
                                       if row.get("access_status") == "ACTIVE")}


def check(registry_path: Path | None = None, sources_path: Path | None = None) -> dict:
    registry = load(registry_path)
    sources = json.loads((sources_path or ROOT / "sources.json").read_text(
        encoding="utf-8"))["sources"]
    errors = validate(registry, sources)
    return {"status": "REGISTRY_OK" if not errors else "REGISTRY_INVALID",
            **summary(registry), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = check(args.registry, args.sources)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "REGISTRY_OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
