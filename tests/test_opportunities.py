from arbitrageve.db.database import Base
from arbitrageve.db.models import Item, MarketOrder
from arbitrageve.services.opportunities import find_opportunities
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_order_book_depth_changes_effective_prices():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(Item(type_id=34, name="Tritanium", volume=0.01))
    session.add_all(
        [
            MarketOrder(
                order_id=1, region_id=10000002, system_id=1, location_id=1,
                type_id=34, price=5, volume_remain=100, volume_total=100,
                is_buy_order=False, collected_at=None,
            ),
            MarketOrder(
                order_id=2, region_id=10000002, system_id=1, location_id=1,
                type_id=34, price=6, volume_remain=100, volume_total=100,
                is_buy_order=False, collected_at=None,
            ),
            MarketOrder(
                order_id=3, region_id=10000043, system_id=2, location_id=2,
                type_id=34, price=8, volume_remain=100, volume_total=100,
                is_buy_order=True, collected_at=None,
            ),
            MarketOrder(
                order_id=4, region_id=10000043, system_id=2, location_id=2,
                type_id=34, price=7, volume_remain=100, volume_total=100,
                is_buy_order=True, collected_at=None,
            ),
        ]
    )
    session.commit()

    result = find_opportunities(
        session, 10000002, 10000043, capital_isk=1100, cargo_m3=1.5,
        min_roi=0.0, min_profit_isk=0,
    )

    assert len(result) == 1
    opportunity = result[0]
    assert opportunity["quantity"] == 150
    assert opportunity["buy_cost"] == 800
    assert opportunity["sell_revenue"] == 1150
    assert opportunity["gross_profit"] == 350
    assert opportunity["roi"] == 0.4375



def test_net_profit_applies_sales_tax_and_transport():
    from arbitrageve.market.costs import TradeCosts

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(Item(type_id=35, name="Test Item", volume=1.0))
    session.add_all(
        [
            MarketOrder(
                order_id=11, region_id=10000002, system_id=1, location_id=10,
                type_id=35, price=100, volume_remain=10, volume_total=10,
                is_buy_order=False, collected_at=None,
            ),
            MarketOrder(
                order_id=12, region_id=10000043, system_id=2, location_id=20,
                type_id=35, price=150, volume_remain=10, volume_total=10,
                is_buy_order=True, collected_at=None,
            ),
        ]
    )
    session.commit()

    result = find_opportunities(
        session,
        10000002,
        10000043,
        capital_isk=1_000,
        cargo_m3=10,
        min_roi=0.0,
        min_profit_isk=0,
        costs=TradeCosts(sales_tax_rate=0.10, transport_flat_isk=50),
    )

    assert len(result) == 1
    opportunity = result[0]
    assert opportunity["buy_cost"] == 1_000
    assert opportunity["sell_revenue"] == 1_500
    assert opportunity["sales_tax"] == 150
    assert opportunity["transport_cost"] == 50
    assert opportunity["net_profit"] == 300
    assert opportunity["roi"] == 0.3
