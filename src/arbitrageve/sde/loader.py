from __future__ import annotations

import json
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from arbitrageve.db.models import Item

LATEST_SDE_URL = (
    "https://developers.eveonline.com/static-data/"
    "eve-online-static-data-latest-jsonl.zip"
)


def download_latest_sde(destination: Path) -> Path:
    """Download the official latest EVE SDE archive."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(LATEST_SDE_URL, headers={"User-Agent": "ArbitrageVE/0.3.0"})
    with urlopen(request, timeout=120) as response, destination.open("wb") as output:
        output.write(response.read())
    return destination


def _find_member(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.endswith(suffix)]
    if not matches:
        raise FileNotFoundError(f"SDE member not found: {suffix}")
    return matches[0]


def load_types_from_archive(archive_path: Path, session: Session) -> int:
    """Load type IDs, names and volumes from the official JSONL SDE."""
    with zipfile.ZipFile(archive_path) as archive:
        member = _find_member(archive, "types.jsonl")
        count = 0
        with archive.open(member) as stream:
            for raw_line in stream:
                if not raw_line.strip():
                    continue
                record = json.loads(raw_line)
                type_id = int(record["_key"])
                value = record["_value"]
                name = value.get("name") or value.get("nameID")
                volume = value.get("volume")
                if not name or volume is None:
                    continue
                session.merge(Item(type_id=type_id, name=str(name), volume=float(volume)))
                count += 1
    session.commit()
    return count


def load_types(archive_path: Path, session: Session) -> int:
    return load_types_from_archive(archive_path, session)
