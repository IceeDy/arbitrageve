from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from arbitrageve.config.settings import settings


class Base(DeclarativeBase):
    pass


def _prepare_database_url(database_url: str) -> str:
    """Normalize and validate the PostgreSQL SQLAlchemy URL."""
    parsed = urlparse(database_url)
    if parsed.scheme == "postgresql":
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if parsed.scheme == "postgresql+psycopg":
        return database_url
    raise ValueError(
        "ArbitrageVE requires PostgreSQL via SQLAlchemy/psycopg. "
        "Set DATABASE_URL to a postgresql:// or postgresql+psycopg:// URL."
    )


DATABASE_URL = _prepare_database_url(settings.database_url)
engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    from arbitrageve import db as _db_package  # noqa: F401
    from arbitrageve.db import models as _models  # noqa: F401

    Base.metadata.create_all(engine)
