from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from arbitrageve.config.settings import settings

class Base(DeclarativeBase): pass
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine)

def init_db(): Base.metadata.create_all(engine)
