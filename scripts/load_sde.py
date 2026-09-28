from pathlib import Path

from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.sde.loader import (
    download_latest_sde,
    load_solar_systems_from_archive,
    load_types,
)


if __name__ == "__main__":
    init_db()
    archive = Path("data/eve-sde-latest.zip")
    download_latest_sde(archive)
    with SessionLocal() as session:
        item_count = load_types(archive, session)
        system_count = load_solar_systems_from_archive(archive, session)
    print(f"Loaded {item_count:,} item types")
    print(f"Loaded {system_count:,} solar systems")
