from datetime import UTC, datetime

from sqlalchemy import func, select

from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.db.models import (
    AppState,
    Item,
    MarketOrder,
    Region,
    SolarSystem,
    Stargate,
)
from arbitrageve.services.market_worker import audit_region_refresh


def main() -> int:
    init_db()
    with SessionLocal() as session:
        counts = {
            "items": session.scalar(select(func.count()).select_from(Item)) or 0,
            "regions": session.scalar(select(func.count()).select_from(Region)) or 0,
            "systems": session.scalar(select(func.count()).select_from(SolarSystem)) or 0,
            "stargates": session.scalar(select(func.count()).select_from(Stargate)) or 0,
            "orders": session.scalar(select(func.count()).select_from(MarketOrder)) or 0,
        }
        sde_loaded = session.scalar(
            select(AppState.value).where(AppState.key == "sde.loaded_at")
        )
        worker_status = session.scalar(
            select(AppState.value).where(AppState.key == "market_worker.status")
        )
        latest_market = session.scalar(
            select(func.max(MarketOrder.collected_at)).select_from(MarketOrder)
        )
        market_regions = session.scalar(
            select(func.count(func.distinct(MarketOrder.region_id)))
        ) or 0
        market_types = session.scalar(
            select(func.count(func.distinct(MarketOrder.type_id)))
        ) or 0
        refresh_audit = audit_region_refresh(session)
        buy_orders = session.scalar(
            select(func.count()).select_from(MarketOrder).where(MarketOrder.is_buy_order.is_(True))
        ) or 0
        sell_orders = session.scalar(
            select(func.count()).select_from(MarketOrder).where(MarketOrder.is_buy_order.is_(False))
        ) or 0

    print("ArbitragEVE production health")
    for key, value in counts.items():
        print(f"{key}: {value:,}")
    print(f"market_regions: {market_regions:,}")
    print(f"market_types: {market_types:,}")
    print(f"buy_orders: {buy_orders:,}")
    print(f"sell_orders: {sell_orders:,}")
    print(f"sde_loaded_at: {sde_loaded or 'MISSING'}")
    print(f"worker_status: {worker_status or 'UNKNOWN'}")
    print(f"latest_market_snapshot: {latest_market or 'MISSING'}")

    refresh_counts = {}
    overdue_regions = []
    for row in refresh_audit:
        status = row["status"]
        refresh_counts[status] = refresh_counts.get(status, 0) + 1
        if status == "DUE":
            overdue_regions.append(
                f"{row['region']} ({row['age_minutes']:.1f}m / "
                f"{row['target_refresh_minutes']:.1f}m)"
            )
    print(
        "market_refresh_status: "
        + ", ".join(
            f"{status}={count}" for status, count in sorted(refresh_counts.items())
        )
    )
    if overdue_regions:
        print("market_refresh_due_regions: " + ", ".join(overdue_regions))

    universe_ready = all(
        counts[key] > 0 for key in ("items", "regions", "systems", "stargates")
    )
    market_ready = (
        counts["orders"] > 0
        and latest_market is not None
        and market_regions > 0
        and market_types > 0
        and buy_orders > 0
        and sell_orders > 0
    )

    if not universe_ready:
        print("FAIL: SDE universe is incomplete.")
        return 1
    if not market_ready:
        print("FAIL: market snapshots are incomplete.")
        return 2

    if latest_market.tzinfo is None:
        age_minutes = (
            datetime.now(UTC).replace(tzinfo=None) - latest_market
        ).total_seconds() / 60
    else:
        age_minutes = (datetime.now(UTC) - latest_market).total_seconds() / 60

    print(f"latest_market_age_minutes: {age_minutes:.1f}")
    if age_minutes > 180:
        print("FAIL: latest market snapshot is older than 180 minutes.")
        return 3

    print("OK: persistent data is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
