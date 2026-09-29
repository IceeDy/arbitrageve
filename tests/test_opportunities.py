from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from arbitrageve.db.database import Base
from arbitrageve.db.models import Item, MarketOrder
from arbitrageve.market.execution import simulate_order_book_execution
from arbitrageve.services.opportunities import (
    calculate_operational_score,
    discover_global_candidates,
    find_global_opportunities,
    find_opportunities,
)

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
    assert opportunity["roi"] == 0.3296875



def test_isk_per_hour_uses_same_return_trip_time_as_estimated_minutes():
    from arbitrageve.market.metrics import ExecutionProfile, estimate_minutes

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(Item(type_id=39, name="ISK/h consistency", volume=1.0))
    session.add_all(
        [
            MarketOrder(
                order_id=391, region_id=10000002, system_id=1, location_id=10,
                type_id=39, price=100, volume_remain=10, volume_total=10,
                is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
            ),
            MarketOrder(
                order_id=392, region_id=10000043, system_id=2, location_id=20,
                type_id=39, price=150, volume_remain=10, volume_total=10,
                is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
            ),
        ]
    )
    session.commit()

    profile = ExecutionProfile(
        fixed_minutes=10.0,
        minutes_per_jump=2.0,
        return_trip=True,
    )
    result = find_opportunities(
        session,
        10000002,
        10000043,
        capital_isk=1_200,
        cargo_m3=10,
        min_roi=0.0,
        min_profit_isk=0,
        execution_profile=profile,
    )

    assert len(result) == 1
    opportunity = result[0]
    expected_minutes = estimate_minutes(opportunity["jumps"], profile)
    assert opportunity["estimated_minutes"] == expected_minutes
    assert opportunity["isk_per_hour"] == (
        opportunity["net_profit"] / expected_minutes * 60
    )

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
        capital_isk=1_200,
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
        capital_isk=11_200,
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

def test_execution_class_distinguishes_speculative_and_scalable_trades():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add_all([
        Item(type_id=42, name="Speculative", volume=1.0),
        Item(type_id=43, name="Scalable", volume=1.0),
    ])
    session.add_all([
        MarketOrder(order_id=71, region_id=10000002, system_id=1, location_id=10,
                    type_id=42, price=100, volume_remain=2, volume_total=2,
                    is_buy_order=False, collected_at=FRESH_COLLECTED_AT),
        MarketOrder(order_id=72, region_id=10000043, system_id=2, location_id=20,
                    type_id=42, price=200, volume_remain=2, volume_total=2,
                    is_buy_order=True, collected_at=FRESH_COLLECTED_AT),
        MarketOrder(order_id=73, region_id=10000002, system_id=1, location_id=10,
                    type_id=43, price=100, volume_remain=250, volume_total=250,
                    is_buy_order=False, collected_at=FRESH_COLLECTED_AT),
        MarketOrder(order_id=74, region_id=10000043, system_id=2, location_id=20,
                    type_id=43, price=150, volume_remain=250, volume_total=250,
                    is_buy_order=True, collected_at=FRESH_COLLECTED_AT),
    ])
    session.commit()

    result = find_opportunities(
        session, 10000002, 10000043, capital_isk=100_000, cargo_m3=200,
        min_roi=0.0, min_profit_isk=0, limit=10,
    )
    by_name = {row["name"]: row for row in result}

    speculative = by_name["Speculative"]
    assert speculative["quantity"] == 2
    assert speculative["execution_class"] == "Especulativa"
    assert speculative["scalable"] is False
    assert speculative["min_executable_quantity"] == 2
    assert speculative["profit_per_unit"] == speculative["net_profit"] / 2

    scalable = by_name["Scalable"]
    assert scalable["quantity"] == 200
    assert scalable["execution_class"] == "Escalável"
    assert scalable["scalable"] is True
    assert scalable["min_executable_quantity"] == 200
    assert scalable["profit_per_unit"] == scalable["net_profit"] / 200


def test_operational_score_is_transparent_and_rewards_execution_quality():
    scalable = calculate_operational_score({
        "execution_class": "Escalável",
        "liquidity_class": "Alta",
        "roi": 0.30,
        "isk_per_hour": 10_000_000,
        "book_coverage": 0.20,
        "risk_score": 0.10,
    })
    speculative = calculate_operational_score({
        "execution_class": "Especulativa",
        "liquidity_class": "Muito baixa",
        "roi": 3.00,
        "isk_per_hour": 10_000_000,
        "book_coverage": 1.00,
        "risk_score": 0.10,
    })

    assert 0 <= scalable["operational_score"] <= 100
    assert scalable["operational_score"] > speculative["operational_score"]
    assert scalable["score_execution"] == 100.0
    assert scalable["score_liquidity"] == 100.0


def test_order_book_execution_simulation_reports_each_consumed_level():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(Item(type_id=44, name="Execution Test", volume=1.0))
    session.add_all([
        MarketOrder(
            order_id=81, region_id=10000002, system_id=1, location_id=10,
            type_id=44, price=100, volume_remain=100, volume_total=100,
            is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
        ),
        MarketOrder(
            order_id=82, region_id=10000002, system_id=1, location_id=10,
            type_id=44, price=110, volume_remain=50, volume_total=50,
            is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
        ),
        MarketOrder(
            order_id=83, region_id=10000043, system_id=2, location_id=20,
            type_id=44, price=160, volume_remain=75, volume_total=75,
            is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
        ),
        MarketOrder(
            order_id=84, region_id=10000043, system_id=2, location_id=20,
            type_id=44, price=150, volume_remain=75, volume_total=75,
            is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
        ),
    ])
    session.commit()

    from arbitrageve.market.costs import TradeCosts

    source = session.query(MarketOrder).filter_by(
        region_id=10000002, type_id=44, is_buy_order=False
    ).order_by(MarketOrder.price.asc()).all()
    destination = session.query(MarketOrder).filter_by(
        region_id=10000043, type_id=44, is_buy_order=True
    ).order_by(MarketOrder.price.desc()).all()

    result = simulate_order_book_execution(
        source, destination, quantity=125, volume_m3=1.0, jumps=5,
        costs=TradeCosts(sales_tax_rate=0.10),
    )

    assert result["quantity"] == 125
    assert result["buy_cost"] == 12_750
    assert result["sell_revenue"] == 19_500
    assert result["avg_buy_price"] == 102.0
    assert result["avg_sell_price"] == 156.0
    assert result["buy_levels_used"] == 2
    assert result["sell_levels_used"] == 2
    assert result["buy_marginal_price"] == 110
    assert result["sell_marginal_price"] == 150
    assert result["top_buy_price"] == 100
    assert result["top_sell_price"] == 160
    assert result["buy_slippage_isk"] == 2.0
    assert result["sell_slippage_isk"] == 4.0
    assert result["buy_slippage_pct"] == 0.02
    assert result["sell_slippage_pct"] == 0.025
    assert result["buy_book_coverage"] == 125 / 150
    assert result["sell_book_coverage"] == 125 / 150
    assert result["sales_tax"] == 1_950
    assert result["net_profit"] == 4_800


def test_opportunity_exposes_execution_levels_and_marginal_prices():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(Item(type_id=45, name="Execution Opportunity", volume=1.0))
    session.add_all([
        MarketOrder(
            order_id=91, region_id=10000002, system_id=1, location_id=10,
            type_id=45, price=100, volume_remain=100, volume_total=100,
            is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
        ),
        MarketOrder(
            order_id=92, region_id=10000002, system_id=1, location_id=10,
            type_id=45, price=120, volume_remain=100, volume_total=100,
            is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
        ),
        MarketOrder(
            order_id=93, region_id=10000043, system_id=2, location_id=20,
            type_id=45, price=150, volume_remain=100, volume_total=100,
            is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
        ),
        MarketOrder(
            order_id=94, region_id=10000043, system_id=2, location_id=20,
            type_id=45, price=140, volume_remain=100, volume_total=100,
            is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
        ),
    ])
    session.commit()

    result = find_opportunities(
        session, 10000002, 10000043, capital_isk=30_000, cargo_m3=150,
        min_roi=0.0, min_profit_isk=0,
    )

    opportunity = result[0]
    assert opportunity["quantity"] == 150
    assert opportunity["buy_levels_used"] == 2
    assert opportunity["sell_levels_used"] == 2
    assert opportunity["buy_marginal_price"] == 120
    assert opportunity["sell_marginal_price"] == 140
    assert opportunity["top_buy_price"] == 100
    assert opportunity["top_sell_price"] == 150
    assert opportunity["buy_slippage_isk"] == (16000 / 150) - 100
    assert opportunity["sell_slippage_isk"] == 150 - (22000 / 150)
    assert opportunity["buy_slippage_pct"] == ((16000 / 150) - 100) / 100
    assert opportunity["sell_slippage_pct"] == (150 - (22000 / 150)) / 150
    assert opportunity["buy_book_coverage"] == 150 / 200
    assert opportunity["sell_book_coverage"] == 150 / 200
    assert [level["quantity"] for level in opportunity["buy_levels"]] == [100, 50]
    assert [level["quantity"] for level in opportunity["sell_levels"]] == [100, 50]


def test_discover_global_candidates_finds_cross_region_pairs():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(Item(type_id=100, name="Global Item", volume=1.0))
    session.add_all([
        MarketOrder(
            order_id=1001, region_id=10000002, system_id=1, location_id=10,
            type_id=100, price=100, volume_remain=50, volume_total=50,
            is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
        ),
        MarketOrder(
            order_id=1002, region_id=10000043, system_id=2, location_id=20,
            type_id=100, price=150, volume_remain=75, volume_total=75,
            is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
        ),
        MarketOrder(
            order_id=1003, region_id=10000032, system_id=3, location_id=30,
            type_id=100, price=140, volume_remain=20, volume_total=20,
            is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
        ),
    ])
    session.commit()

    candidates = discover_global_candidates(
        session, min_roi=0.0, min_profit_isk=0.0, max_candidates=10
    )

    assert len(candidates) == 2
    assert all(row["type_id"] == 100 for row in candidates)
    assert {
        (row["source_region_id"], row["destination_region_id"])
        for row in candidates
    } == {
        (10000002, 10000043),
        (10000002, 10000032),
    }


def test_find_global_opportunities_uses_global_candidate_discovery():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(Item(type_id=101, name="Global Execution", volume=1.0))
    session.add_all([
        MarketOrder(
            order_id=1011, region_id=10000002, system_id=1, location_id=10,
            type_id=101, price=100, volume_remain=10, volume_total=10,
            is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
        ),
        MarketOrder(
            order_id=1012, region_id=10000043, system_id=2, location_id=20,
            type_id=101, price=150, volume_remain=10, volume_total=10,
            is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
        ),
    ])
    session.commit()

    class DirectRoute:
        def route(self, origin, destination, **kwargs):
            return [origin, destination]

    diagnostics = {}
    result = find_global_opportunities(
        session,
        capital_isk=2_000,
        cargo_m3=10,
        min_roi=0.0,
        min_profit_isk=0,
        route_client=DirectRoute(),
        diagnostics=diagnostics,
        max_candidates=10,
    )

    assert len(result) == 1
    assert result[0]["name"] == "Global Execution"
    assert result[0]["source_region_id"] == 10000002
    assert result[0]["destination_region_id"] == 10000043
    assert diagnostics["global_candidates"] == 1
    assert diagnostics["detailed_scans"] == 1


def test_discover_global_candidates_filters_by_capital_cargo_and_profit():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Item(type_id=200, name="Bounded Item", volume=10.0))
    session.add_all([
        MarketOrder(
            order_id=2001, region_id=10000002, system_id=1, location_id=10,
            type_id=200, price=100, volume_remain=100, volume_total=100,
            is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
        ),
        MarketOrder(
            order_id=2002, region_id=10000043, system_id=2, location_id=20,
            type_id=200, price=400, volume_remain=100, volume_total=100,
            is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
        ),
    ])
    session.commit()

    candidates = discover_global_candidates(
        session,
        min_roi=0.0,
        min_profit_isk=1_000,
        capital_isk=2_000,
        cargo_m3=50,
        max_candidates=10,
    )

    assert len(candidates) == 1
    assert candidates[0]["max_quantity_bound"] == 5
    assert candidates[0]["optimistic_profit"] == 1350.0


def test_execution_auditor_verifies_capital_cargo_book_costs_and_levels():
    from arbitrageve.services.opportunities import audit_opportunity_execution

    opportunity = {
        "quantity": 100,
        "buy_cost": 10_000.0,
        "sell_revenue": 12_000.0,
        "total_costs": 900.0,
        "net_profit": 1_100.0,
        "capital_required": 10_900.0,
        "volume_m3": 50.0,
        "source_book_volume": 200,
        "destination_book_volume": 150,
        "buy_levels": [{"quantity": 100}],
        "sell_levels": [{"quantity": 100}],
        "route_system_ids": [1, 2, 3],
        "route_known": True,
        "jumps": 2,
        "route_class": "highsec",
        "market_age_minutes": 10.0,
        "capital_efficiency": 0.11,
        "roi": 0.11,
    }

    audit = audit_opportunity_execution(
        opportunity,
        capital_isk=12_000,
        cargo_m3=100,
        max_market_age_minutes=60,
    )

    assert audit["execution_verified"] is True
    assert audit["execution_audit_issues"] == []
    assert audit["capital_headroom"] == 1_100
    assert audit["cargo_headroom_m3"] == 50
    assert audit["book_headroom"] == 50
    assert audit["capital_efficiency_equals_roi"] is True


def test_execution_auditor_rejects_partial_or_unknown_route():
    from arbitrageve.services.opportunities import audit_opportunity_execution

    opportunity = {
        "quantity": 10,
        "buy_cost": 1_000.0,
        "sell_revenue": 1_500.0,
        "total_costs": 100.0,
        "net_profit": 400.0,
        "capital_required": 1_100.0,
        "volume_m3": 10.0,
        "source_book_volume": 10,
        "destination_book_volume": 10,
        "buy_levels": [{"quantity": 10}],
        "sell_levels": [{"quantity": 10}],
        "route_system_ids": [1],
        "route_known": False,
        "jumps": 3,
        "route_class": "highsec",
        "market_age_minutes": 5.0,
        "capital_efficiency": 0.4,
        "roi": 0.4,
    }

    audit = audit_opportunity_execution(
        opportunity,
        capital_isk=2_000,
        cargo_m3=10,
        max_market_age_minutes=60,
    )

    assert audit["execution_verified"] is False
    assert "route" in audit["execution_audit_issues"]


def test_execution_auditor_detects_capital_cargo_book_and_stale_market():
    from arbitrageve.services.opportunities import audit_opportunity_execution

    opportunity = {
        "quantity": 20,
        "buy_cost": 2_000.0,
        "sell_revenue": 3_000.0,
        "total_costs": 100.0,
        "net_profit": 900.0,
        "capital_required": 2_100.0,
        "volume_m3": 25.0,
        "source_book_volume": 10,
        "destination_book_volume": 15,
        "buy_levels": [{"quantity": 20}],
        "sell_levels": [{"quantity": 20}],
        "route_system_ids": [1, 2],
        "route_known": True,
        "jumps": 1,
        "route_class": "highsec",
        "market_age_minutes": 120.0,
        "capital_efficiency": 0.45,
        "roi": 0.45,
    }

    audit = audit_opportunity_execution(
        opportunity,
        capital_isk=2_000,
        cargo_m3=10,
        max_market_age_minutes=60,
    )

    assert audit["execution_verified"] is False
    assert {"capital", "cargo", "order_book", "market_freshness"} <= set(
        audit["execution_audit_issues"]
    )


def test_global_sort_by_isk_per_hour_uses_route_aware_execution_time():
    from arbitrageve.market.metrics import ExecutionProfile

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add_all([
        Item(type_id=102, name="Fast Global", volume=1.0),
        Item(type_id=103, name="Slow Global", volume=1.0),
    ])
    session.add_all([
        MarketOrder(
            order_id=1021, region_id=10000002, system_id=1, location_id=10,
            type_id=102, price=100, volume_remain=10, volume_total=10,
            is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
        ),
        MarketOrder(
            order_id=1022, region_id=10000043, system_id=2, location_id=20,
            type_id=102, price=150, volume_remain=10, volume_total=10,
            is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
        ),
        MarketOrder(
            order_id=1031, region_id=10000002, system_id=1, location_id=10,
            type_id=103, price=100, volume_remain=10, volume_total=10,
            is_buy_order=False, collected_at=FRESH_COLLECTED_AT,
        ),
        MarketOrder(
            order_id=1032, region_id=10000032, system_id=3, location_id=30,
            type_id=103, price=150, volume_remain=10, volume_total=10,
            is_buy_order=True, collected_at=FRESH_COLLECTED_AT,
        ),
        SolarSystem(
            system_id=1, name="Source", security_status=1.0, security_class="highsec"
        ),
        SolarSystem(
            system_id=2, name="Fast Destination", security_status=1.0,
            security_class="highsec"
        ),
        SolarSystem(
            system_id=3, name="Slow Destination", security_status=1.0,
            security_class="highsec"
        ),
    ])
    session.commit()

    class RouteByDestination:
        def route(self, origin, destination, **kwargs):
            if destination == 2:
                return [origin, destination]
            return [origin, 11, 12, 13, 14, 15, 16, 17, 18, 19, destination]

    result = find_global_opportunities(
        session,
        capital_isk=2_000,
        cargo_m3=10,
        min_roi=0.0,
        min_profit_isk=0,
        route_client=RouteByDestination(),
        execution_profile=ExecutionProfile(
            fixed_minutes=10.0,
            minutes_per_jump=2.0,
            return_trip=False,
        ),
        sort_by="isk_per_hour",
        max_candidates=10,
    )

    assert len(result) == 2
    assert result[0]["name"] == "Fast Global"
    assert result[1]["name"] == "Slow Global"
    assert result[0]["net_profit"] == result[1]["net_profit"]
    assert result[0]["estimated_minutes"] < result[1]["estimated_minutes"]
    assert result[0]["isk_per_hour"] > result[1]["isk_per_hour"]
