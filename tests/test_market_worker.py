from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import sessionmaker

from arbitrageve.config.settings import settings
from arbitrageve.db.database import Base
from arbitrageve.db.models import AppState, MarketOrder, Region
from arbitrageve.services.market_worker import (
from tests.db import create_test_engine
    calculate_region_refresh_minutes,
    select_regions_for_refresh,
)


def _session():
    engine = create_test_engine()
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_select_regions_prioritizes_overdue_configured_hubs():
    session = _session()
    now = datetime.now(UTC).replace(tzinfo=None)

    forge = Region(region_id=10000002, name="The Forge")
    domain = Region(region_id=10000043, name="Domain")
    remote = Region(region_id=10000070, name="Genesis")
    session.add_all([forge, domain, remote])
    session.commit()

    session.add_all(
        [
            MarketOrder(
                order_id=1,
                region_id=forge.region_id,
                system_id=30000001,
                location_id=60000001,
                type_id=34,
                price=1,
                volume_remain=1,
                volume_total=1,
                is_buy_order=False,
                collected_at=now - timedelta(minutes=90),
            ),
            MarketOrder(
                order_id=2,
                region_id=domain.region_id,
                system_id=30000002,
                location_id=60000002,
                type_id=34,
                price=1,
                volume_remain=1,
                volume_total=1,
                is_buy_order=False,
                collected_at=now - timedelta(minutes=90),
            ),
        ]
    )
    session.commit()

    old_refresh = settings.market_refresh_minutes
    old_min = settings.market_refresh_min_minutes
    old_max = settings.market_refresh_max_minutes
    old_reference = settings.market_refresh_reference_orders
    old_exponent = settings.market_refresh_order_exponent
    old_limit = settings.market_max_regions_per_run
    old_priority = settings.market_region_priority
    try:
        settings.market_refresh_minutes = 60
        settings.market_refresh_min_minutes = 15
        settings.market_refresh_max_minutes = 360
        settings.market_refresh_reference_orders = 1
        settings.market_refresh_order_exponent = 0.5
        settings.market_max_regions_per_run = 3
        settings.market_region_priority = "The Forge,Domain"
        selected = select_regions_for_refresh(session)
    finally:
        settings.market_refresh_minutes = old_refresh
        settings.market_refresh_min_minutes = old_min
        settings.market_refresh_max_minutes = old_max
        settings.market_refresh_reference_orders = old_reference
        settings.market_refresh_order_exponent = old_exponent
        settings.market_max_regions_per_run = old_limit
        settings.market_region_priority = old_priority

    assert [region.name for region in selected] == ["The Forge", "Domain", "Genesis"]


def test_select_regions_keeps_fresh_regions_after_overdue_regions():
    session = _session()
    now = datetime.now(UTC).replace(tzinfo=None)
    session.add_all(
        [
            Region(region_id=1, name="Fresh"),
            Region(region_id=2, name="Old"),
        ]
    )
    session.commit()

    session.add(
        MarketOrder(
            order_id=10,
            region_id=1,
            system_id=30000001,
            location_id=60000001,
            type_id=34,
            price=1,
            volume_remain=1,
            volume_total=1,
            is_buy_order=False,
            collected_at=now - timedelta(minutes=5),
        )
    )
    session.commit()

    old_refresh = settings.market_refresh_minutes
    old_reference = settings.market_refresh_reference_orders
    old_exponent = settings.market_refresh_order_exponent
    try:
        settings.market_refresh_minutes = 30
        settings.market_refresh_reference_orders = 1
        settings.market_refresh_order_exponent = 0.0
        selected = select_regions_for_refresh(session, limit=1)
    finally:
        settings.market_refresh_minutes = old_refresh
        settings.market_refresh_reference_orders = old_reference
        settings.market_refresh_order_exponent = old_exponent

    assert [region.name for region in selected] == ["Old"]


def test_refresh_interval_decreases_as_order_volume_increases():
    old_min = settings.market_refresh_min_minutes
    old_max = settings.market_refresh_max_minutes
    old_reference = settings.market_refresh_reference_orders
    old_exponent = settings.market_refresh_order_exponent
    try:
        settings.market_refresh_min_minutes = 15
        settings.market_refresh_max_minutes = 360
        settings.market_refresh_reference_orders = 100
        settings.market_refresh_order_exponent = 0.5

        low_volume = calculate_region_refresh_minutes(100)
        high_volume = calculate_region_refresh_minutes(400)
        huge_volume = calculate_region_refresh_minutes(1_000_000)
    finally:
        settings.market_refresh_min_minutes = old_min
        settings.market_refresh_max_minutes = old_max
        settings.market_refresh_reference_orders = old_reference
        settings.market_refresh_order_exponent = old_exponent

    assert low_volume == settings.market_refresh_minutes
    assert high_volume < low_volume
    assert huge_volume == 15


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
                MarketOrder(
                    order_id=1000 + index,
                    region_id=high.region_id,
                    system_id=30000001,
                    location_id=60000001,
                    type_id=34,
                    price=1,
                    volume_remain=1,
                    volume_total=1,
                    is_buy_order=False,
                    collected_at=now - timedelta(minutes=40),
                )
                for index in range(400)
            ],
            MarketOrder(
                order_id=2000,
                region_id=low.region_id,
                system_id=30000002,
                location_id=60000002,
                type_id=34,
                price=1,
                volume_remain=1,
                volume_total=1,
                is_buy_order=False,
                collected_at=now - timedelta(minutes=40),
            ),
        ]
    )
    session.commit()

    old_refresh = settings.market_refresh_minutes
    old_min = settings.market_refresh_min_minutes
    old_max = settings.market_refresh_max_minutes
    old_reference = settings.market_refresh_reference_orders
    old_exponent = settings.market_refresh_order_exponent
    try:
        settings.market_refresh_minutes = 60
        settings.market_refresh_min_minutes = 15
        settings.market_refresh_max_minutes = 360
        settings.market_refresh_reference_orders = 100
        settings.market_refresh_order_exponent = 0.5
        selected = select_regions_for_refresh(session, limit=2)
    finally:
        settings.market_refresh_minutes = old_refresh
        settings.market_refresh_min_minutes = old_min
        settings.market_refresh_max_minutes = old_max
        settings.market_refresh_reference_orders = old_reference
        settings.market_refresh_order_exponent = old_exponent

    assert [region.name for region in selected] == ["High Volume"]


def test_collect_priority_regions_persists_worker_health(monkeypatch):
    from arbitrageve.services import market_worker

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
