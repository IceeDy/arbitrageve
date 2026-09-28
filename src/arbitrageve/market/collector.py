from datetime import datetime, timezone

from arbitrageve.db.models import MarketOrder
from arbitrageve.esi.market import MarketClient


def collect_region(session, region_id: int, client: MarketClient | None = None) -> int:
    """Collect all market orders for a region, preserving the collection timestamp."""
    client = client or MarketClient()
    stamp = datetime.now(timezone.utc).replace(tzinfo=None)
    total = 0

    _, pages = client.get_orders(region_id, page=1)
    for page in range(1, pages + 1):
        orders, _ = client.get_orders(region_id, page=page)
        for data in orders:
            issued = data.get("issued")
            if issued:
                issued = datetime.fromisoformat(
                    issued.replace("Z", "+00:00")
                ).replace(tzinfo=None)

            session.merge(
                MarketOrder(
                    order_id=data["order_id"],
                    region_id=region_id,
                    system_id=data["system_id"],
                    location_id=data["location_id"],
                    type_id=data["type_id"],
                    price=data["price"],
                    volume_remain=data["volume_remain"],
                    volume_total=data["volume_total"],
                    is_buy_order=data["is_buy_order"],
                    issued=issued,
                    duration=data.get("duration"),
                    collected_at=stamp,
                )
            )
            total += 1
        session.commit()

    return total
