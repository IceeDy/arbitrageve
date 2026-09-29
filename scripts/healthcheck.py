from datetime import UTC, datetime

from sqlalchemy import func, select

from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.db.models import AppState, Item, MarketOrder, Region, SolarSystem, Stargate


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

    print("ArbitragEVE production health")
    for key, value in counts.items():
        print(f"{key}: {value:,}")
    print(f"sde_loaded_at: {sde_loaded or 'MISSING'}")
    print(f"worker_status: {worker_status or 'UNKNOWN'}")
    print(f"latest_market_snapshot: {latest_market or 'MISSING'}")

    universe_ready = all(counts[key] > 0 for key in ("items", "regions", "systems", "stargates"))
    market_ready = counts["orders"] > 0 and latest_market is not None

    if not universe_ready:
        print("FAIL: SDE universe is incomplete.")
        return 1
    if not market_ready:
        print("FAIL: market snapshots are empty.")
        return 2

    if latest_market.tzinfo is None:
        age_minutes = (datetime.now(UTC).replace(tzinfo=None) - latest_market).total_seconds() / 60
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
