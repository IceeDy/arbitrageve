from __future__ import annotations

from datetime import UTC, datetime

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


def calculate_region_refresh_minutes(order_count: int) -> float:
    """Return the target refresh interval for a region.

    More orders mean more market state to keep current. The square-root
    scaling avoids making very large regions impossible to maintain while
    still giving them substantially shorter refresh intervals.
    """
    if order_count <= 0:
        return float(settings.market_refresh_max_minutes)

    reference = max(1, settings.market_refresh_reference_orders)
    exponent = max(0.0, settings.market_refresh_order_exponent)
    interval = settings.market_refresh_minutes * (
        reference / max(order_count, 1)
    ) ** exponent
    return min(
        float(settings.market_refresh_max_minutes),
        max(float(settings.market_refresh_min_minutes), interval),
    )


def _region_market_rows(session) -> list[tuple[Region, datetime | None, int]]:
    return session.execute(
        select(
            Region,
            func.max(MarketOrder.collected_at).label("last_collected"),
            func.count(MarketOrder.order_id).label("order_count"),
        )
        .outerjoin(MarketOrder, MarketOrder.region_id == Region.region_id)
        .group_by(Region.region_id)
    ).all()


def audit_region_refresh(session) -> list[dict[str, object]]:
    """Return operational refresh state for every known region."""
    priority = _priority_map()
    now = datetime.now(UTC).replace(tzinfo=None)
    audit: list[dict[str, object]] = []

    for region, last_collected, order_count in _region_market_rows(session):
        refresh_minutes = calculate_region_refresh_minutes(order_count)
        if last_collected is None:
            age_minutes = None
            overdue_ratio = None
            status = "NEVER"
        else:
            age_minutes = max(
                0.0,
                (now - last_collected).total_seconds() / 60,
            )
            overdue_ratio = (
                age_minutes / refresh_minutes if refresh_minutes else float("inf")
            )
            status = "DUE" if age_minutes >= refresh_minutes else "FRESH"

        audit.append(
            {
                "region_id": region.region_id,
                "region": region.name,
                "order_count": order_count,
                "last_collected": last_collected,
                "age_minutes": age_minutes,
                "target_refresh_minutes": refresh_minutes,
                "overdue_ratio": overdue_ratio,
                "priority": priority.get(region.name.lower(), 10_000),
                "status": status,
            }
        )

    audit.sort(
        key=lambda row: (
            0 if row["status"] == "DUE" else 1 if row["status"] == "NEVER" else 2,
            -(row["overdue_ratio"] or 0.0),
            row["priority"],
            row["region"],
        )
    )
    return audit


def select_regions_for_refresh(session, limit: int | None = None) -> list[Region]:
    """Select regions whose adaptive refresh interval has elapsed."""
    limit = limit or settings.market_max_regions_per_run
    priority = _priority_map()
    now = datetime.now(UTC).replace(tzinfo=None)

    due_rows = []
    for region, last_collected, order_count in _region_market_rows(session):
        refresh_minutes = calculate_region_refresh_minutes(order_count)
        age_minutes = (
            float("inf")
            if last_collected is None
            else max(0.0, (now - last_collected).total_seconds() / 60)
        )
        if last_collected is None or age_minutes >= refresh_minutes:
            overdue_ratio = (
                1.0
                if last_collected is None
                else age_minutes / refresh_minutes
                if refresh_minutes
                else float("inf")
            )
            due_rows.append(
                (
                    region,
                    overdue_ratio,
                    priority.get(region.name.lower(), 10_000),
                    age_minutes,
                )
            )

    due_rows.sort(key=lambda row: (-row[1], row[2], -row[3]))
    return [row[0] for row in due_rows[:limit]]


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
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        _set_worker_state(
            session,
            "market_worker.last_finished_at",
            finished_at.isoformat(timespec="seconds"),
        )
        _set_worker_state(session, "market_worker.status", "OK")
        _set_worker_state(session, "market_worker.last_error", "")
        return results
    except Exception as exc:
        _set_worker_state(session, "market_worker.status", "ERROR")
        _set_worker_state(session, "market_worker.last_error", str(exc)[:450])
        raise
