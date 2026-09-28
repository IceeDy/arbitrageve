from arbitrageve.db.database import Base
from arbitrageve.db.models import Item, MarketOrder
from arbitrageve.services.opportunities import find_opportunities
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_cross_region_opportunity():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(Item(type_id=34, name="Tritanium", volume=0.01))
    session.add_all(
        [
            MarketOrder(
                order_id=1, region_id=10000002, system_id=30000142,
                location_id=60003760, type_id=34, price=5,
                volume_remain=1000, volume_total=1000, is_buy_order=False,
                collected_at=None,
            ),
            MarketOrder(
                order_id=2, region_id=10000043, system_id=30002187,
                location_id=60008494, type_id=34, price=8,
                volume_remain=1000, volume_total=1000, is_buy_order=True,
                collected_at=None,
            ),
        ]
    )
    session.commit()

    result = find_opportunities(
        session, 10000002, 10000043, capital_isk=1000, cargo_m3=100,
        min_roi=0.1, min_profit_isk=100,
    )

    assert len(result) == 1
    assert result[0]["name"] == "Tritanium"
    assert result[0]["quantity"] == 200
    assert result[0]["net_profit"] == 600
    assert result[0]["roi"] == 0.6
