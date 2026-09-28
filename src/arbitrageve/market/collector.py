from datetime import datetime, timezone

from sqlalchemy import delete

from arbitrageve.db.models import MarketOrder
from arbitrageve.esi.market import MarketClient


def collect_region(
    session,
    region_id: int,
    client: MarketClient | None = None,
    progress_callback=None,
) -> int:
    """Replace a region with one complete ESI market snapshot.

    Page 1 is used to discover the current page count and is then reused,
    avoiding a duplicate request. Existing rows are deleted only after every
    page has been fetched successfully.
    """
    client = client or MarketClient()
    stamp = datetime.now(timezone.utc).replace(tzinfo=None)

    first_page, pages = client.get_orders(region_id, page=1)
    collected = list(first_page)

    if progress_callback:
        progress_callback(1, pages, len(collected))

    for page in range(2, pages + 1):
        orders, _ = client.get_orders(region_id, page=page)
        collected.extend(orders)
        if progress_callback:
            progress_callback(page, pages, len(collected))

    session.execute(delete(MarketOrder).where(MarketOrder.region_id == region_id))

    for data in collected:
        issued = data.get("issued")
        if issued:
            issued = datetime.fromisoformat(
                issued.replace("Z", "+00:00")
            ).replace(tzinfo=None)

        session.add(
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

    session.commit()
    return len(collected)
