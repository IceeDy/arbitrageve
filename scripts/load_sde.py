from pathlib import Path

from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.sde.loader import (
    download_latest_sde,
    load_regions_from_archive,
    load_solar_systems_from_archive,
    load_stargates_from_archive,
    load_types,
)

if __name__ == "__main__":
    init_db()
    archive = Path("data/eve-sde-latest.zip")
    download_latest_sde(archive)
    with SessionLocal() as session:
        region_count = load_regions_from_archive(archive, session)
        item_count = load_types(archive, session)
        system_count = load_solar_systems_from_archive(archive, session)
        stargate_count = load_stargates_from_archive(archive, session)

    print(f"Loaded {region_count:,} regions")
    print(f"Loaded {item_count:,} item types")
    print(f"Loaded {system_count:,} solar systems")
    print(f"Loaded {stargate_count:,} stargates")
