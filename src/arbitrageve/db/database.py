from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine
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
    """Prepare a writable SQLite location when running in hosted environments."""
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
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    Base.metadata.create_all(engine)
