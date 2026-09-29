

from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.services.market_worker import collect_priority_regions
if __name__ == "__main__":
    init_db()
    with SessionLocal() as session:
        results = collect_priority_regions(session)
        if not results:
            print("No regions require refresh.")
        for region_id, count in results.items():
            print(f"Region {region_id}: {count:,} orders")
