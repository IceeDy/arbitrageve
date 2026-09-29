from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from arbitrageve.config.settings import settings
from arbitrageve.db.models import AppState, MarketOrder, Region
from arbitrageve.market.collector import collect_region


def _priority_map() -> dict[str, int]:
    names = [
        name.strip().lower()
        for name in settings.market_region_priority.split(",")
        if name.strip()
    ]
    return {name: index for index, name in enumerate(names)}


def select_regions_for_refresh(session, limit: int | None = None) -> list[Region]:
    """Select only the stalest overdue regions for one worker cycle."""
    limit = limit or settings.market_max_regions_per_run
    priority = _priority_map()
    now = datetime.now(UTC).replace(tzinfo=None)
    cutoff = now - timedelta(minutes=settings.market_refresh_minutes)

    rows = session.execute(
        select(Region, func.max(MarketOrder.collected_at).label("last_collected"))
        .outerjoin(MarketOrder, MarketOrder.region_id == Region.region_id)
        .group_by(Region.region_id)
    ).all()

    def sort_key(row):
        region, last_collected = row
        overdue = last_collected is None or last_collected < cutoff
        configured = priority.get(region.name.lower(), 10_000)
        fallback = datetime.min.replace(tzinfo=UTC).replace(tzinfo=None)
        return (
            0 if overdue else 1,
            configured,
            last_collected or fallback,
        )

    rows.sort(key=sort_key)
    return [row[0] for row in rows[:limit]]


def _set_worker_state(session, key: str, value: str) -> None:
    state = session.get(AppState, key)
    now = datetime.now(UTC).replace(tzinfo=None)
    if state is None:
        session.add(AppState(key=key, value=value, updated_at=now))
    else:
        state.value = value
        state.updated_at = now
    session.commit()


def collect_priority_regions(session, limit: int | None = None) -> dict[int, int]:
    """Refresh overdue regions and persist worker health state."""
    started_at = datetime.now(UTC).replace(tzinfo=None)
    _set_worker_state(
        session,
        "market_worker.last_started_at",
        started_at.isoformat(timespec="seconds"),
    )
    _set_worker_state(session, "market_worker.status", "RUNNING")
    results: dict[int, int] = {}
    try:
        for region in select_regions_for_refresh(session, limit):
            results[region.region_id] = collect_region(session, region.region_id)
        _set_worker_state(session, "market_worker.last_regions", ",".join(map(str, results)))
        _set_worker_state(session, "market_worker.last_finished_at", datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"))
        _set_worker_state(session, "market_worker.status", "OK")
        _set_worker_state(session, "market_worker.last_error", "")
        return results
    except Exception as exc:
        _set_worker_state(session, "market_worker.status", "ERROR")
        _set_worker_state(session, "market_worker.last_error", str(exc)[:450])
        raise
