from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from arbitrageve.config.settings import settings
from arbitrageve.db.models import MarketOrder, Region
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
        fallback = datetime.min.replace(tzinfo=None)
        return (
            0 if overdue else 1,
            configured,
            last_collected or fallback,
        )

    rows.sort(key=sort_key)
    return [row[0] for row in rows[:limit]]


def collect_priority_regions(session, limit: int | None = None) -> dict[int, int]:
    results: dict[int, int] = {}
    for region in select_regions_for_refresh(session, limit):
        results[region.region_id] = collect_region(session, region.region_id)
    return results
