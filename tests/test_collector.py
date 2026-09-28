from arbitrageve.market.collector import collect_region
from arbitrageve.db.database import Base
from arbitrageve.db.models import MarketOrder
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


class FakeResponse:
    def __init__(self, payload, pages):
        self.payload = payload
        self.pages = pages

    def json(self):
        return self.payload

    @property
    def headers(self):
        return {"X-Pages": str(self.pages)}


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_orders(self, region_id, order_type="all", page=1):
        self.calls.append((region_id, page))
        rows = {
            1: [
                {
                    "order_id": 101,
                    "system_id": 30000142,
                    "location_id": 60003760,
                    "type_id": 34,
                    "price": 5.0,
                    "volume_remain": 100,
                    "volume_total": 100,
                    "is_buy_order": False,
                    "issued": "2026-09-28T10:00:00Z",
                    "duration": 90,
                }
            ],
            2: [
                {
                    "order_id": 102,
                    "system_id": 30000142,
                    "location_id": 60003760,
                    "type_id": 34,
                    "price": 6.0,
                    "volume_remain": 50,
                    "volume_total": 50,
                    "is_buy_order": False,
                    "issued": "2026-09-28T10:00:00Z",
                    "duration": 90,
                }
            ],
        }
        return rows.get(page, []), 2


def test_collect_region_reuses_first_page_and_replaces_snapshot():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    client = FakeClient()

    session.add(
        MarketOrder(
            order_id=999,
            region_id=10000002,
            system_id=1,
            location_id=1,
            type_id=34,
            price=1,
            volume_remain=1,
            volume_total=1,
            is_buy_order=False,
            collected_at=None,
        )
    )
    session.commit()

    count = collect_region(session, 10000002, client)

    assert count == 2
    assert client.calls == [(10000002, 1), (10000002, 2)]

    orders = session.scalars(
        select(MarketOrder).where(MarketOrder.region_id == 10000002)
    ).all()
    assert {order.order_id for order in orders} == {101, 102}


class DuplicatePageClient(FakeClient):
    def get_orders(self, region_id, order_type="all", page=1):
        rows, pages = super().get_orders(region_id, order_type, page)
        if page == 2:
            rows = rows + [rows[0]]
        return rows, pages


def test_collect_region_deduplicates_overlapping_pages():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    count = collect_region(session, 10000002, DuplicatePageClient())

    assert count == 2
    orders = session.scalars(select(MarketOrder)).all()
    assert len(orders) == 2
