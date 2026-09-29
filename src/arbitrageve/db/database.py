from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from arbitrageve.config.settings import settings


class Base(DeclarativeBase):
    pass


def _sqlite_path(database_url: str) -> Path | None:
    """Return the filesystem path for a SQLite URL, if applicable."""
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        return None
    path = parsed.path
    if path == ":memory:":
        return None
    if path.startswith("/") and parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    return Path(path).expanduser()


def _prepare_database_url(database_url: str) -> str:
    """Prepare a writable SQLite location and normalize PostgreSQL URLs."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    path = _sqlite_path(database_url)
    if path is None:
        return database_url
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / ".arbitrageve-write-test"
        probe.touch()
        probe.unlink()
        return f"sqlite:///{path}"
    except OSError:
        fallback = Path("/tmp/arbitrageve/arbitrageve.db")
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{fallback}"


DATABASE_URL = _prepare_database_url(settings.database_url)
engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine)


def _migrate_sqlite_schema() -> None:
    """Apply small additive migrations for existing local SQLite databases."""
    if not DATABASE_URL.startswith("sqlite:"):
        return

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "solar_systems" in tables:
        columns = {column["name"] for column in inspector.get_columns("solar_systems")}
        if "region_id" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE solar_systems ADD COLUMN region_id INTEGER")
                )


def init_db() -> None:
    from arbitrageve import db as _db_package  # noqa: F401
    from arbitrageve.db import models as _models  # noqa: F401

    Base.metadata.create_all(engine)
    _migrate_sqlite_schema()
