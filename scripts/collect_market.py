from arbitrageve.config.regions import DOMAIN, THE_FORGE
from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.market.collector import collect_region

if __name__ == '__main__':
    init_db()
    with SessionLocal() as session:
        print('Domain:', collect_region(session, DOMAIN))
        print('The Forge:', collect_region(session, THE_FORGE))
