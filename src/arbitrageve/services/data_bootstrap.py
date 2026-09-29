from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from arbitrageve.db.models import AppState, Item, Region, SolarSystem, Stargate
from arbitrageve.sde.loader import (
    LOADER_VERSION,
    download_latest_sde,
    load_regions_from_archive,
    load_solar_systems_from_archive,
    load_stargates_from_archive,
    load_types,
)

SDE_STATE_KEY = "sde.loader_version"


def get_state(session, key: str) -> str | None:
    state = session.get(AppState, key)
    return state.value if state else None


def set_state(session, key: str, value: str) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    state = session.get(AppState, key)
    if state is None:
        session.add(AppState(key=key, value=value, updated_at=now))
    else:
        state.value = value
        state.updated_at = now
    session.commit()


def sde_ready(session) -> bool:
    return all(
        value is not None
        for value in (
            session.scalar(select(Item.type_id).limit(1)),
            session.scalar(select(Region.region_id).limit(1)),
            session.scalar(select(SolarSystem.system_id).limit(1)),
            session.scalar(select(Stargate.stargate_id).limit(1)),
        )
    )


def ensure_sde(session, archive_path: Path | None = None, force: bool = False) -> bool:
    """Load the official SDE only when the persistent database needs it."""
    if not force and get_state(session, SDE_STATE_KEY) == LOADER_VERSION and sde_ready(session):
        return False

    archive = archive_path or Path("/tmp/arbitrageve/eve-sde-latest.zip")
    download_latest_sde(archive)
    load_types(archive, session)
    load_regions_from_archive(archive, session)
    load_solar_systems_from_archive(archive, session)
    load_stargates_from_archive(archive, session)

    set_state(session, SDE_STATE_KEY, LOADER_VERSION)
    set_state(
        session,
        "sde.loaded_at",
        datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
    )
    return True
