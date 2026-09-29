from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from arbitrageve.db.database import Base
from arbitrageve.db.models import MarketOrder
from arbitrageve.market.collector import collect_region, collect_regions


from tests.db import create_test_engine


class FakeMarketClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get_orders(self, region_id, page=1):
        self.calls.append((region_id, page))
        orders = self.pages[page - 1]
        return orders, len(self.pages)


def _session():
    engine = create_test_engine()
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _order(order_id, *, price=100.0, issued="2026-09-28T12:00:00Z"):
    return {
        "order_id": order_id,
        "system_id": 30000001,
        "location_id": 60000001,
        "type_id": 34,
        "price": price,
        "volume_remain": 10,
        "volume_total": 20,
        "is_buy_order": False,
        "issued": issued,
        "duration": 90,
    }


def test_collect_region_fetches_all_pages_and_replaces_snapshot():
    session = _session()
    session.add(
        MarketOrder(
            order_id=999,
            region_id=10000002,
            system_id=30000099,
            location_id=60000099,
            type_id=34,
            price=1,
            volume_remain=1,
            volume_total=1,
            is_buy_order=False,
            collected_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    session.commit()

    client = FakeMarketClient(
        [
            [_order(1, price=5)],
            [_order(2, price=6)],
            [_order(3, price=7)],
        ]
    )
    progress = []

    count = collect_region(
        session,
        10000002,
        client=client,
        progress_callback=lambda page, pages, orders: progress.append(
            (page, pages, orders)
        ),
    )

    assert count == 3
    assert client.calls == [
        (10000002, 1),
        (10000002, 2),
        (10000002, 3),
    ]
    assert progress == [(1, 3, 1), (2, 3, 2), (3, 3, 3)]

    orders = session.scalars(
        select(MarketOrder)
        .where(MarketOrder.region_id == 10000002)
        .order_by(MarketOrder.order_id)
    ).all()

    assert [order.order_id for order in orders] == [1, 2, 3]
    assert all(order.collected_at == orders[0].collected_at for order in orders)


def test_collect_region_deduplicates_overlapping_pages():
    session = _session()
    client = FakeMarketClient(
        [
            [_order(10, price=5)],
            [_order(10, price=6), _order(11, price=7)],
        ]
    )

    count = collect_region(session, 10000002, client=client)

    assert count == 2
    orders = session.scalars(
        select(MarketOrder)
        .where(MarketOrder.region_id == 10000002)
        .order_by(MarketOrder.order_id)
    ).all()

    assert [order.order_id for order in orders] == [10, 11]
    assert orders[0].price == 6


def test_collect_region_preserves_order_fields_and_parses_issued_timestamp():
    session = _session()
    client = FakeMarketClient([[_order(20, price=123.45)]])

    count = collect_region(session, 10000043, client=client)

    assert count == 1
    order = session.scalar(
        select(MarketOrder).where(MarketOrder.order_id == 20)
    )

    assert order.region_id == 10000043
    assert order.system_id == 30000001
    assert order.location_id == 60000001
    assert order.type_id == 34
    assert order.price == 123.45
    assert order.volume_remain == 10
    assert order.volume_total == 20
    assert order.is_buy_order is False
    assert order.duration == 90
    assert order.issued == datetime(2026, 9, 28, 12, 0, tzinfo=UTC).replace(tzinfo=None)


def test_collect_regions_deduplicates_region_ids_and_collects_each():
    session = _session()

    class RegionAwareFakeClient:
        def __init__(self):
            self.calls = []

        def get_orders(self, region_id, page=1):
            self.calls.append((region_id, page))
            return [_order(region_id, price=5)], 1

    client = RegionAwareFakeClient()
    results = collect_regions(
        session,
        [10000002, 10000043, 10000002],
        client=client,
    )

    assert results == {10000002: 1, 10000043: 1}
    assert client.calls == [
        (10000002, 1),
        (10000043, 1),
    ]
