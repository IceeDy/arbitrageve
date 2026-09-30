import os
from uuid import uuid4

from sqlalchemy import create_engine, text

from arbitrageve.db.database import Base

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/arbitrageve_test",
)


def create_test_engine():
    """Create an isolated PostgreSQL schema for one test engine."""
    schema = f"test_{uuid4().hex}"

    admin_engine = create_engine(
        TEST_DATABASE_URL,
        future=True,
        pool_pre_ping=True,
    )
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    admin_engine.dispose()

    engine = create_engine(
        TEST_DATABASE_URL,
        future=True,
        pool_pre_ping=True,
        connect_args={"options": f'-c search_path="{schema}",public'},
    )
    Base.metadata.create_all(engine)
    return engine
