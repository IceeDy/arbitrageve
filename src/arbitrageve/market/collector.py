from datetime import UTC, datetime

from sqlalchemy import delete

from arbitrageve.db.models import MarketOrder
from arbitrageve.esi.market import MarketClient


def _deduplicate_orders(orders: list[dict]) -> list[dict]:
    """Keep one record per ESI order ID."""
    unique: dict[int, dict] = {}
    for order in orders:
        unique[order["order_id"]] = order
    return list(unique.values())


def collect_region(
    session,
    region_id: int,
    client: MarketClient | None = None,
    progress_callback=None,
) -> int:
    """Replace one region with a complete ESI market snapshot."""
    client = client or MarketClient()
    stamp = datetime.now(UTC).replace(tzinfo=None)

    first_page, pages = client.get_orders(region_id, page=1)
    collected = list(first_page)
    if progress_callback:
        progress_callback(1, pages, len(collected))

    for page in range(2, pages + 1):
        orders, _ = client.get_orders(region_id, page=page)
        collected.extend(orders)
        if progress_callback:
            progress_callback(page, pages, len(collected))

    collected = _deduplicate_orders(collected)
    session.execute(delete(MarketOrder).where(MarketOrder.region_id == region_id))

    for data in collected:
        issued = data.get("issued")
        if issued:
            issued = datetime.fromisoformat(issued).replace(tzinfo=None)
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


def collect_regions(
    session,
    region_ids,
    client: MarketClient | None = None,
    progress_callback=None,
) -> dict[int, int]:
    """Collect multiple regions without hard-coding a market universe."""
    results: dict[int, int] = {}
    region_ids = list(dict.fromkeys(int(region_id) for region_id in region_ids))

    for index, region_id in enumerate(region_ids, start=1):
        if progress_callback:
            progress_callback(index, len(region_ids), region_id)
        results[region_id] = collect_region(
            session,
            region_id,
            client=client,
        )

    return results
