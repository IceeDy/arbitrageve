from __future__ import annotations

import json
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from arbitrageve.db.models import Item, SolarSystem

LATEST_SDE_URL = (
    "https://developers.eveonline.com/static-data/"
    "eve-online-static-data-latest-jsonl.zip"
)
LOADER_VERSION = "2026-09-28-sde-debug-1"


def download_latest_sde(destination: Path) -> Path:
    """Download the official latest EVE SDE archive."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(
        LATEST_SDE_URL,
        headers={"User-Agent": "ArbitrageVE/0.4.0"},
    )
    with urlopen(request, timeout=120) as response, destination.open("wb") as output:
        output.write(response.read())
    return destination


def _find_member(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.endswith(suffix)]
    if not matches:
        raise FileNotFoundError(f"SDE member not found: {suffix}")
    if len(matches) > 1:
        exact = [name for name in matches if Path(name).name == suffix]
        if len(exact) == 1:
            return exact[0]
        raise RuntimeError(f"Multiple SDE members match {suffix}: {matches[:10]}")
    return matches[0]


def _value(record: dict) -> dict:
    """Return the payload for both current and legacy JSONL record shapes."""
    value = record.get("_value")
    if isinstance(value, dict):
        return value
    return record


def _localized_name(value: object) -> str | None:
    """Extract an English/display name from current SDE name shapes."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("en", "en-us", "en_US"):
            name = value.get(key)
            if isinstance(name, str) and name.strip():
                return name.strip()
        for candidate in value.values():
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def _record_name(value: dict) -> str | None:
    for key in ("name", "displayName", "typeName"):
        name = _localized_name(value.get(key))
        if name:
            return name
    return None


def inspect_types_archive(archive_path: Path) -> dict:
    """Inspect the types JSONL shape without touching the database."""
    with zipfile.ZipFile(archive_path) as archive:
        member = _find_member(archive, "types.jsonl")
        lines = 0
        keyed = 0
        named = 0
        samples = []

        with archive.open(member) as stream:
            for raw_line in stream:
                if not raw_line.strip():
                    continue
                lines += 1
                record = json.loads(raw_line)
                if "_key" in record:
                    keyed += 1
                value = _value(record)
                if _record_name(value):
                    named += 1
                if len(samples) < 3:
                    samples.append(record)
                if lines >= 100:
                    break

    return {
        "loader_version": LOADER_VERSION,
        "member": member,
        "sample_lines": lines,
        "sample_keyed": keyed,
        "sample_named": named,
        "samples": samples,
    }


def load_types_from_archive(archive_path: Path, session: Session) -> int:
    """Load type IDs, names and volumes from the current official JSONL SDE."""
    with zipfile.ZipFile(archive_path) as archive:
        member = _find_member(archive, "types.jsonl")
        count = 0
        with archive.open(member) as stream:
            for raw_line in stream:
                if not raw_line.strip():
                    continue

                record = json.loads(raw_line)
                if "_key" not in record:
                    continue

                type_id = int(record["_key"])
                value = _value(record)
                name = _record_name(value)
                volume = value.get("volume")
                if volume is None:
                    volume = value.get("packagedVolume")
                if volume is None:
                    volume = 0.0

                if not name:
                    continue

                session.merge(
                    Item(
                        type_id=type_id,
                        name=name,
                        volume=float(volume),
                    )
                )
                count += 1

    session.commit()
    return count


def load_solar_systems_from_archive(archive_path: Path, session: Session) -> int:
    """Load solar-system names and security status from the official JSONL SDE."""
    with zipfile.ZipFile(archive_path) as archive:
        member = _find_member(archive, "mapSolarSystems.jsonl")
        count = 0
        with archive.open(member) as stream:
            for raw_line in stream:
                if not raw_line.strip():
                    continue

                record = json.loads(raw_line)
                system_id = int(record["_key"])
                value = _value(record)

                name = _record_name(value)
                security_status = value.get("securityStatus")
                if not name or security_status is None:
                    continue

                session.merge(
                    SolarSystem(
                        system_id=system_id,
                        name=name,
                        security_status=float(security_status),
                    )
                )
                count += 1

    session.commit()
    return count


def load_types(archive_path: Path, session: Session) -> int:
    return load_types_from_archive(archive_path, session)
