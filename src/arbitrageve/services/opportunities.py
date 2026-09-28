from dataclasses import asdict

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from arbitrageve.db.models import Item, MarketOrder


def _consume_orders(orders, quantity: int):
    remaining = quantity
    spent = 0.0
    acquired = 0
    for order in orders:
        take = min(remaining, order.volume_remain)
        spent += take * order.price
        acquired += take
        remaining -= take
        if remaining <= 0:
            break
    return acquired, spent


def _sell_orders(orders, quantity: int):
    remaining = quantity
    revenue = 0.0
    sold = 0
    for order in orders:
        take = min(remaining, order.volume_remain)
        revenue += take * order.price
        sold += take
        remaining -= take
        if remaining <= 0:
            break
    return sold, revenue


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
    """Find executable cross-region opportunities using order-book depth.

    Buys consume source sell orders from cheapest to most expensive.
    Sales consume destination buy orders from highest to lowest.
    Capital and cargo constraints are applied before profitability is evaluated.
    """
    item_ids = session.execute(
        select(MarketOrder.type_id)
        .where(
            MarketOrder.region_id.in_(
                [source_region_id, destination_region_id]
            )
        )
        .distinct()
    ).scalars().all()

    results = []

    for type_id in item_ids:
        item = session.get(Item, type_id)

        source_orders = session.scalars(
            select(MarketOrder)
            .where(
                and_(
                    MarketOrder.region_id == source_region_id,
                    MarketOrder.type_id == type_id,
                    MarketOrder.is_buy_order.is_(False),
                    MarketOrder.volume_remain > 0,
                )
            )
            .order_by(MarketOrder.price.asc())
        ).all()

        destination_orders = session.scalars(
            select(MarketOrder)
            .where(
                and_(
                    MarketOrder.region_id == destination_region_id,
                    MarketOrder.type_id == type_id,
                    MarketOrder.is_buy_order.is_(True),
                    MarketOrder.volume_remain > 0,
                )
            )
            .order_by(MarketOrder.price.desc())
        ).all()

        if not source_orders or not destination_orders:
            continue

        volume = item.volume if item else 0.0
        if volume <= 0 or cargo_m3 <= 0 or capital_isk <= 0:
            continue

        max_by_cargo = int(cargo_m3 // volume)
        if max_by_cargo <= 0:
            continue

        # Start with the maximum feasible quantity and reduce it until
        # both sides of the order book can execute the complete trade.
        max_quantity = max_by_cargo
        source_available = sum(o.volume_remain for o in source_orders)
        destination_available = sum(o.volume_remain for o in destination_orders)
        max_quantity = min(max_quantity, source_available, destination_available)

        if max_quantity <= 0:
            continue

        # Capital is evaluated against the actual weighted source cost,
        # not merely the cheapest order price.
        quantity = max_quantity
        while quantity > 0:
            acquired, spent = _consume_orders(source_orders, quantity)
            sold, revenue = _sell_orders(destination_orders, quantity)

            if acquired == quantity and sold == quantity and spent <= capital_isk:
                break

            quantity = min(quantity - 1, acquired, sold)
            if spent > capital_isk:
                quantity = min(quantity, int(capital_isk // source_orders[0].price))

        if quantity <= 0:
            continue

        # Recalculate on the final executable quantity.
        _, spent = _consume_orders(source_orders, quantity)
        _, revenue = _sell_orders(destination_orders, quantity)
        gross_profit = revenue - spent
        roi = gross_profit / spent if spent else 0.0
        volume_m3 = quantity * volume

        if roi < min_roi or gross_profit < min_profit_isk:
            continue

        results.append(
            {
                "type_id": type_id,
                "name": item.name if item else f"type:{type_id}",
                "quantity": quantity,
                "buy_cost": spent,
                "sell_revenue": revenue,
                "gross_profit": gross_profit,
                "roi": roi,
                "volume_m3": volume_m3,
                "source_region_id": source_region_id,
                "destination_region_id": destination_region_id,
            }
        )

    return sorted(
        results,
        key=lambda opportunity: opportunity["gross_profit"],
        reverse=True,
    )[:limit]
