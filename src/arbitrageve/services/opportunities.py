from dataclasses import asdict

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from arbitrageve.db.models import Item, MarketOrder
from arbitrageve.market.arbitrage import calculate_opportunity


def find_opportunities(
    session: Session,
    source_region_id: int,
    destination_region_id: int,
    capital_isk: float,
    cargo_m3: float,
    min_roi: float = 0.05,
    min_profit_isk: float = 100_000,
    limit: int = 100,
) -> list[dict]:
    """Find cross-region opportunities using current collected sell orders.

    Source = where we buy from sell orders.
    Destination = where we sell using buy orders.
    """
    source = (
        select(
            MarketOrder.type_id,
            func.min(MarketOrder.price).label("buy_price"),
            func.sum(MarketOrder.volume_remain).label("source_volume"),
        )
        .where(
            and_(
                MarketOrder.region_id == source_region_id,
                MarketOrder.is_buy_order.is_(False),
            )
        )
        .group_by(MarketOrder.type_id)
        .subquery()
    )
    destination = (
        select(
            MarketOrder.type_id,
            func.max(MarketOrder.price).label("sell_price"),
            func.sum(MarketOrder.volume_remain).label("destination_volume"),
        )
        .where(
            and_(
                MarketOrder.region_id == destination_region_id,
                MarketOrder.is_buy_order.is_(True),
            )
        )
        .group_by(MarketOrder.type_id)
        .subquery()
    )

    rows = session.execute(
        select(
            source.c.type_id,
            Item.name,
            Item.volume,
            source.c.buy_price,
            destination.c.sell_price,
            source.c.source_volume,
            destination.c.destination_volume,
        )
        .join(destination, destination.c.type_id == source.c.type_id)
        .join(Item, Item.type_id == source.c.type_id, isouter=True)
    ).all()

    results: list[dict] = []
    for row in rows:
        if row.buy_price <= 0 or row.sell_price <= row.buy_price:
            continue

        quantity = min(
            int(capital_isk // row.buy_price),
            int(row.source_volume or 0),
            int(row.destination_volume or 0),
        )
        if quantity <= 0:
            continue

        opportunity = calculate_opportunity(
            row.type_id,
            row.buy_price,
            row.sell_price,
            quantity,
            row.volume or 0,
        )
        if opportunity.roi < min_roi or opportunity.net_profit < min_profit_isk:
            continue
        if opportunity.volume_m3 > cargo_m3:
            quantity = min(quantity, int(cargo_m3 // max(row.volume or 0.000001, 0.000001)))
            if quantity <= 0:
                continue
            opportunity = calculate_opportunity(
                row.type_id,
                row.buy_price,
                row.sell_price,
                quantity,
                row.volume or 0,
            )

        result = asdict(opportunity)
        result.update(
            {
                "name": row.name or f"type:{row.type_id}",
                "source_region_id": source_region_id,
                "destination_region_id": destination_region_id,
            }
        )
        results.append(result)

    return sorted(results, key=lambda x: x["net_profit"], reverse=True)[:limit]
