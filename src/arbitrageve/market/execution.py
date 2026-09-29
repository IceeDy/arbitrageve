from __future__ import annotations

from typing import Any

from arbitrageve.market.costs import TradeCosts, calculate_trade_costs


def _consume_levels(orders, quantity: int) -> tuple[list[dict[str, Any]], int, float]:
    remaining = quantity
    executed = 0
    total = 0.0
    levels: list[dict[str, Any]] = []

    for order in orders:
        if remaining <= 0:
            break
        take = min(remaining, order.volume_remain)
        if take <= 0:
            continue
        value = take * order.price
        levels.append(
            {
                "order_id": order.order_id,
                "price": order.price,
                "quantity": take,
                "value": value,
                "remaining_before": order.volume_remain,
                "consumed_pct": take / order.volume_remain if order.volume_remain else 0.0,
            }
        )
        executed += take
        total += value
        remaining -= take

    return levels, executed, total


def simulate_order_book_execution(
    source_orders,
    destination_orders,
    quantity: int,
    volume_m3: float,
    jumps: int,
    costs: TradeCosts,
) -> dict[str, Any]:
    """Simulate consuming both sides of the order books at the requested quantity."""
    if quantity < 0:
        raise ValueError("quantity cannot be negative")
    if volume_m3 < 0:
        raise ValueError("volume_m3 cannot be negative")

    buy_levels, bought, spent = _consume_levels(source_orders, quantity)
    sell_levels, sold, revenue = _consume_levels(destination_orders, quantity)

    if bought != quantity or sold != quantity:
        raise ValueError("order books cannot execute the requested quantity")

    trade_costs = calculate_trade_costs(
        revenue,
        quantity * volume_m3,
        jumps,
        costs,
    )
    gross_profit = revenue - spent
    net_profit = gross_profit - trade_costs["total_costs"]

    avg_buy_price = spent / quantity if quantity else 0.0
    avg_sell_price = revenue / quantity if quantity else 0.0
    top_buy_price = source_orders[0].price if source_orders else None
    top_sell_price = destination_orders[0].price if destination_orders else None
    buy_slippage_isk = (
        avg_buy_price - top_buy_price
        if top_buy_price is not None
        else 0.0
    )
    sell_slippage_isk = (
        top_sell_price - avg_sell_price
        if top_sell_price is not None
        else 0.0
    )
    buy_slippage_pct = buy_slippage_isk / top_buy_price if top_buy_price else 0.0
    sell_slippage_pct = sell_slippage_isk / top_sell_price if top_sell_price else 0.0
    source_depth = sum(order.volume_remain for order in source_orders)
    destination_depth = sum(order.volume_remain for order in destination_orders)

    return {
        "quantity": quantity,
        "buy_cost": spent,
        "sell_revenue": revenue,
        "avg_buy_price": avg_buy_price,
        "avg_sell_price": avg_sell_price,
        "top_buy_price": top_buy_price,
        "top_sell_price": top_sell_price,
        "buy_slippage_isk": buy_slippage_isk,
        "sell_slippage_isk": sell_slippage_isk,
        "buy_slippage_pct": buy_slippage_pct,
        "sell_slippage_pct": sell_slippage_pct,
        "buy_book_coverage": quantity / source_depth if source_depth else 0.0,
        "sell_book_coverage": quantity / destination_depth if destination_depth else 0.0,
        "gross_profit": gross_profit,
        "net_profit": net_profit,
        "sales_tax": trade_costs["sales_tax"],
        "broker_fee": trade_costs["broker_fee"],
        "transport_cost": trade_costs["transport_cost"],
        "safety_margin": trade_costs["safety_margin"],
        "total_costs": trade_costs["total_costs"],
        "buy_levels": buy_levels,
        "sell_levels": sell_levels,
        "buy_levels_used": len(buy_levels),
        "sell_levels_used": len(sell_levels),
        "buy_marginal_price": buy_levels[-1]["price"] if buy_levels else None,
        "sell_marginal_price": sell_levels[-1]["price"] if sell_levels else None,
    }
