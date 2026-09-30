from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import sessionmaker

from arbitrageve.config.market_refresh import (
    MARKET_REFRESH_BASE_MINUTES,
    MARKET_REFRESH_MAX_MINUTES,
    MARKET_REFRESH_MIN_MINUTES,
    MARKET_REFRESH_ORDER_EXPONENT,
    MARKET_REFRESH_REFERENCE_ORDERS,
)
from arbitrageve.db.database import Base
from arbitrageve.db.models import AppState, MarketOrder, Region
from arbitrageve.services import market_worker
from arbitrageve.services.market_worker import (
    audit_region_refresh,
    calculate_region_refresh_minutes,
    select_regions_for_refresh,
)
from tests.db import create_test_engine


def _session():
    engine = create_test_engine()
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _order(order_id: int, region_id: int, collected_at: datetime) -> MarketOrder:
    return MarketOrder(
        order_id=order_id,
        region_id=region_id,
        system_id=30000001,
        location_id=60000001,
        type_id=34,
        price=1,
        volume_remain=1,
        volume_total=1,
        is_buy_order=False,
        collected_at=collected_at,
    )


def test_refresh_policy_is_canonical_and_not_settings_driven():
    assert MARKET_REFRESH_BASE_MINUTES == 5
    assert MARKET_REFRESH_MIN_MINUTES == 5
    assert MARKET_REFRESH_MAX_MINUTES == 1440
    assert MARKET_REFRESH_REFERENCE_ORDERS == 50_000
    assert MARKET_REFRESH_ORDER_EXPONENT == 0.5

    assert calculate_region_refresh_minutes(0) == 1440
    assert calculate_region_refresh_minutes(400_000) == 5


def test_refresh_interval_decreases_as_order_volume_increases():
    assert (
        calculate_region_refresh_minutes(100)
        > calculate_region_refresh_minutes(10_000)
        > calculate_region_refresh_minutes(100_000)
    )


def test_select_regions_prioritizes_overdue_high_volume_region():
    session = _session()
    now = datetime.now(UTC).replace(tzinfo=None)
    high = Region(region_id=1, name="High Volume")
    low = Region(region_id=2, name="Low Volume")
    session.add_all([high, low])
    session.commit()

    session.add_all(
        [
            *[
                _order(1000 + index, high.region_id, now - timedelta(minutes=60))
                for index in range(400)
            ],
            _order(2000, low.region_id, now - timedelta(minutes=40)),
        ]
    )
    session.commit()

    selected = select_regions_for_refresh(session, limit=2)

    assert [region.name for region in selected] == ["High Volume"]


def test_audit_region_refresh_uses_canonical_policy_and_daily_empty():
    session = _session()
    now = datetime.now(UTC).replace(tzinfo=None)
    forge = Region(region_id=1, name="The Forge")
    empty = Region(region_id=2, name="Genesis")
    session.add_all([forge, empty])
    session.commit()

    session.add_all(
        [
            _order(1000 + index, forge.region_id, now - timedelta(minutes=60))
            for index in range(400)
        ]
    )
    session.commit()

    by_name = {row["region"]: row for row in audit_region_refresh(session)}

    assert calculate_region_refresh_minutes(400_000) == 5
    assert by_name["The Forge"]["target_refresh_minutes"] == calculate_region_refresh_minutes(400)
    assert by_name["The Forge"]["status"] == "DUE"
    assert by_name["Genesis"]["target_refresh_minutes"] == 1440
    assert by_name["Genesis"]["status"] == "NEVER"


def test_collect_priority_regions_persists_worker_health(monkeypatch):
    session = _session()
    session.add(Region(region_id=10000002, name="The Forge"))
    session.commit()

    monkeypatch.setattr(
        market_worker,
        "collect_region",
        lambda session, region_id: 123,
    )

    result = market_worker.collect_priority_regions(session, limit=1)

    assert result == {10000002: 123}
    assert session.get(AppState, "market_worker.status").value == "OK"
    assert session.get(AppState, "market_worker.last_regions").value == "10000002"
    assert session.get(AppState, "market_worker.last_started_at").value
    assert session.get(AppState, "market_worker.last_finished_at").value
    assert session.get(AppState, "market_worker.last_error").value == ""
