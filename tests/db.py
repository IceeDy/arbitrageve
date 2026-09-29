import os

from sqlalchemy import create_engine

from arbitrageve.db.database import Base

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/arbitrageve_test",
)


def create_test_engine():
    """Create an isolated PostgreSQL test database state."""
    engine = create_engine(TEST_DATABASE_URL, future=True, pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return engine
