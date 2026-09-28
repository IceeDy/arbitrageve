from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from arbitrageve.db.database import Base
from arbitrageve.db.models import Item, MarketOrder
from arbitrageve.services.opportunities import find_opportunities

FRESH_COLLECTED_AT = datetime.now(UTC).replace(tzinfo=None)


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
                is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
            ),
            MarketOrder(
                order_id=2, region_id=10000002, system_id=1, location_id=1,
                type_id=34, price=6, volume_remain=100, volume_total=100,
                is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
            ),
            MarketOrder(
                order_id=3, region_id=10000043, system_id=2, location_id=2,
                type_id=34, price=8, volume_remain=100, volume_total=100,
                is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
            ),
            MarketOrder(
                order_id=4, region_id=10000043, system_id=2, location_id=2,
                type_id=34, price=7, volume_remain=100, volume_total=100,
                is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
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
                is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
            ),
            MarketOrder(
                order_id=12, region_id=10000043, system_id=2, location_id=20,
                type_id=35, price=150, volume_remain=10, volume_total=10,
                is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
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


def test_opportunity_exposes_liquidity_and_spread_metrics():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(Item(type_id=36, name="Liquidity Test", volume=1.0))
    session.add_all(
        [
            MarketOrder(
                order_id=21, region_id=10000002, system_id=1, location_id=10,
                type_id=36, price=100, volume_remain=100, volume_total=100,
                is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
            ),
            MarketOrder(
                order_id=22, region_id=10000002, system_id=1, location_id=10,
                type_id=36, price=110, volume_remain=100, volume_total=100,
                is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
            ),
            MarketOrder(
                order_id=23, region_id=10000043, system_id=2, location_id=20,
                type_id=36, price=150, volume_remain=150, volume_total=150,
                is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
            ),
        ]
    )
    session.commit()

    result = find_opportunities(
        session,
        10000002,
        10000043,
        capital_isk=10_000,
        cargo_m3=150,
        min_roi=0.0,
        min_profit_isk=0,
    )

    opportunity = result[0]
    assert opportunity["source_book_volume"] == 200
    assert opportunity["destination_book_volume"] == 150
    assert opportunity["book_capacity"] == 150
    assert opportunity["quantity"] == 100
    assert opportunity["book_coverage"] == 100 / 150
    assert opportunity["spread_isk"] == 50
    assert opportunity["spread_pct"] == 0.5


def test_sort_by_applies_before_limit():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add_all(
        [
            Item(type_id=37, name="High ROI", volume=1.0),
            Item(type_id=38, name="High Profit", volume=1.0),
        ]
    )
    session.add_all(
        [
            MarketOrder(
                order_id=31, region_id=10000002, system_id=1, location_id=10,
                type_id=37, price=100, volume_remain=10, volume_total=10,
                is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
            ),
            MarketOrder(
                order_id=32, region_id=10000043, system_id=2, location_id=20,
                type_id=37, price=200, volume_remain=10, volume_total=10,
                is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
            ),
            MarketOrder(
                order_id=33, region_id=10000002, system_id=1, location_id=10,
                type_id=38, price=10, volume_remain=1000, volume_total=1000,
                is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
            ),
            MarketOrder(
                order_id=34, region_id=10000043, system_id=2, location_id=20,
                type_id=38, price=11, volume_remain=1000, volume_total=1000,
                is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
            ),
        ]
    )
    session.commit()

    result = find_opportunities(
        session,
        10000002,
        10000043,
        capital_isk=10_000,
        cargo_m3=10,
        min_roi=0.0,
        min_profit_isk=0,
        limit=1,
        sort_by="roi",
    )

    assert len(result) == 1
    assert result[0]["name"] == "High ROI"


def test_capital_sizing_includes_all_modeled_trade_costs():
    from arbitrageve.market.costs import TradeCosts

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(Item(type_id=39, name="Capital Test", volume=1.0))
    session.add_all(
        [
            MarketOrder(
                order_id=41, region_id=10000002, system_id=1, location_id=10,
                type_id=39, price=100, volume_remain=10, volume_total=10,
                is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
            ),
            MarketOrder(
                order_id=42, region_id=10000043, system_id=2, location_id=20,
                type_id=39, price=150, volume_remain=10, volume_total=10,
                is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
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
    assert result[0]["quantity"] == 8
    assert result[0]["buy_cost"] == 800
    assert result[0]["total_costs"] == 170
    assert result[0]["net_profit"] == 230


def test_liquidity_class_uses_absolute_depth_and_book_coverage():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(Item(type_id=40, name="Liquidity Class Test", volume=1.0))
    session.add_all(
        [
            MarketOrder(
                order_id=51, region_id=10000002, system_id=1, location_id=10,
                type_id=40, price=100, volume_remain=2000, volume_total=2000,
                is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
            ),
            MarketOrder(
                order_id=52, region_id=10000043, system_id=2, location_id=20,
                type_id=40, price=150, volume_remain=2000, volume_total=2000,
                is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
            ),
        ]
    )
    session.commit()

    result = find_opportunities(
        session,
        10000002,
        10000043,
        capital_isk=500_000,
        cargo_m3=100,
        min_roi=0.0,
        min_profit_isk=0,
    )

    assert len(result) == 1
    assert result[0]["quantity"] == 100
    assert result[0]["book_capacity"] == 2000
    assert result[0]["book_coverage"] == 0.05
    assert result[0]["liquidity_class"] == "Média"


def test_stale_market_snapshot_is_rejected():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    collected_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
    session.add(Item(type_id=41, name="Stale Market Test", volume=1.0))
    session.add_all(
        [
            MarketOrder(
                order_id=61, region_id=10000002, system_id=1, location_id=10,
                type_id=41, price=100, volume_remain=10, volume_total=10,
                is_buy_order=False, collected_at=collected_at,
            ),
            MarketOrder(
                order_id=62, region_id=10000043, system_id=2, location_id=20,
                type_id=41, price=150, volume_remain=10, volume_total=10,
                is_buy_order=True, collected_at=collected_at,
            ),
        ]
    )
    session.commit()

    diagnostics = {}
    result = find_opportunities(
        session,
        10000002,
        10000043,
        capital_isk=10_000,
        cargo_m3=10,
        min_roi=0.0,
        min_profit_isk=0,
        max_market_age_minutes=60,
        diagnostics=diagnostics,
    )

    assert result == []
    assert diagnostics["rejected_stale_market"] == 1
