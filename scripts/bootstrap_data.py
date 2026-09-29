from pathlib import Path



from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.services.data_bootstrap import ensure_sde
if __name__ == "__main__":
    init_db()
    with SessionLocal() as session:
        changed = ensure_sde(session, Path("/tmp/arbitrageve/eve-sde-latest.zip"))
    print("SDE loaded." if changed else "SDE already current.")
