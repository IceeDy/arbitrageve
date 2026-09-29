import argparse
from pathlib import Path

from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.services.data_bootstrap import ensure_sde


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap or refresh the EVE SDE.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Download and reload the SDE even when the database is already populated.",
    )
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        changed = ensure_sde(
            session,
            Path("/tmp/arbitrageve/eve-sde-latest.zip"),
            force=args.force,
        )
    print("SDE loaded." if changed else "SDE already current.")


if __name__ == "__main__":
    main()
