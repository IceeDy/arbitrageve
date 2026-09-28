from pathlib import Path

from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.sde.loader import download_latest_sde, load_types


if __name__ == "__main__":
    init_db()
    archive = Path("data/eve-sde-latest.zip")
    download_latest_sde(archive)
    with SessionLocal() as session:
        count = load_types(archive, session)
    print(f"Loaded {count:,} item types")
