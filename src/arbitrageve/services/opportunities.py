from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from arbitrageve.db.models import Item, MarketOrder, SolarSystem
from arbitrageve.market.costs import TradeCosts, calculate_trade_costs
from arbitrageve.market.metrics import ExecutionProfile, estimate_isk_per_hour
from arbitrageve.services.risk import RiskProfile, analyze_route, route_allowed


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


def _max_affordable_quantity(
    source_orders,
    destination_orders,
    max_quantity: int,
    capital_isk: float,
    volume_m3: float,
    cargo_m3: float,
    jumps: int,
    costs: TradeCosts,
) -> int:
    """Find the largest executable quantity without decrementing one unit at a time."""
    max_quantity = min(max_quantity, int(cargo_m3 // volume_m3))
    if max_quantity <= 0:
        return 0

    def affordable(quantity: int) -> bool:
        acquired, spent = _consume_orders(source_orders, quantity)
        sold, revenue = _sell_orders(destination_orders, quantity)
        if acquired != quantity or sold != quantity:
            return False
        trade_costs = calculate_trade_costs(revenue, quantity * volume_m3, jumps, costs)
        return spent + trade_costs["broker_fee"] <= capital_isk

    low, high = 0, max_quantity
    while low < high:
        mid = (low + high + 1) // 2
        if affordable(mid):
            low = mid
        else:
            high = mid - 1
    return low


def find_opportunities(
    session: Session,
    source_region_id: int,
    destination_region_id: int,
    capital_isk: float,
    cargo_m3: float,
    min_roi: float = 0.05,
    min_profit_isk: float = 100_000,
    limit: int = 100,
    costs: TradeCosts | None = None,
    route_client=None,
    route_preference: str = "Shorter",
    security_penalty: int = 50,
    risk_profile: RiskProfile | None = None,
    execution_profile: ExecutionProfile | None = None,
) -> list[dict]:
    """Find executable cross-region opportunities using order-book depth."""
    costs = costs or TradeCosts()
    costs.validate()
    risk_profile = risk_profile or RiskProfile()
    risk_profile.validate()
    execution_profile = execution_profile or ExecutionProfile()
    execution_profile.validate()

    item_ids = session.execute(
        select(MarketOrder.type_id)
        .where(MarketOrder.region_id.in_([source_region_id, destination_region_id]))
        .distinct()
    ).scalars().all()

    results = []
    route_cache: dict[tuple[int, int, str, int], tuple[list[int], int]] = {}
    system_cache: dict[int, SolarSystem | None] = {}

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

        source_lane = (source_orders[0].system_id, source_orders[0].location_id)
        destination_lane = (destination_orders[0].system_id, destination_orders[0].location_id)
        source_orders = [o for o in source_orders if (o.system_id, o.location_id) == source_lane]
        destination_orders = [o for o in destination_orders if (o.system_id, o.location_id) == destination_lane]

        origin_system = source_lane[0]
        destination_system = destination_lane[0]
        cache_key = (origin_system, destination_system, route_preference, security_penalty)
        if cache_key not in route_cache:
            if route_client and origin_system != destination_system:
                route = route_client.route(
                    origin_system,
                    destination_system,
                    preference=route_preference,
                    security_penalty=security_penalty,
                )
            else:
                route = [origin_system]
            route_cache[cache_key] = (route, max(0, len(route) - 1))

        route, jumps = route_cache[cache_key]
        systems = []
        for system_id in route:
            if system_id not in system_cache:
                system_cache[system_id] = session.get(SolarSystem, system_id)
            if system_cache[system_id] is not None:
                systems.append(system_cache[system_id])

        risk = analyze_route(systems, jumps)
        risk["jumps"] = jumps
        if not route_allowed(risk_profile, risk):
            continue

        source_available = sum(o.volume_remain for o in source_orders)
        destination_available = sum(o.volume_remain for o in destination_orders)
        max_quantity = min(source_available, destination_available, int(cargo_m3 // volume))
        quantity = _max_affordable_quantity(
            source_orders,
            destination_orders,
            max_quantity,
            capital_isk,
            volume,
            cargo_m3,
            jumps,
            costs,
        )
        if quantity <= 0:
            continue

        _, spent = _consume_orders(source_orders, quantity)
        _, revenue = _sell_orders(destination_orders, quantity)
        trade_costs = calculate_trade_costs(revenue, quantity * volume, jumps, costs)
        gross_profit = revenue - spent
        net_profit = gross_profit - trade_costs["total_costs"]
        roi = net_profit / spent if spent else 0.0
        estimated_minutes = execution_profile.fixed_minutes + jumps * execution_profile.minutes_per_jump
        if execution_profile.return_trip:
            estimated_minutes *= 2
        isk_per_hour = estimate_isk_per_hour(net_profit, jumps, execution_profile)

        if roi < min_roi or net_profit < min_profit_isk:
            continue

        results.append(
            {
                "type_id": type_id,
                "name": item.name if item else f"type:{type_id}",
                "quantity": quantity,
                "buy_cost": spent,
                "sell_revenue": revenue,
                "avg_buy_price": spent / quantity,
                "avg_sell_price": revenue / quantity,
                "gross_profit": gross_profit,
                "sales_tax": trade_costs["sales_tax"],
                "broker_fee": trade_costs["broker_fee"],
                "transport_cost": trade_costs["transport_cost"],
                "safety_margin": trade_costs["safety_margin"],
                "total_costs": trade_costs["total_costs"],
                "net_profit": net_profit,
                "roi": roi,
                "estimated_minutes": estimated_minutes,
                "isk_per_hour": isk_per_hour,
                "volume_m3": quantity * volume,
                "jumps": jumps,
                "route_system_ids": route,
                "route_class": risk["route_class"],
                "highsec_systems": risk["highsec_systems"],
                "lowsec_systems": risk["lowsec_systems"],
                "nullsec_systems": risk["nullsec_systems"],
                "min_security_status": risk["min_security_status"],
                "risk_score": risk["risk_score"],
                "source_system_id": origin_system,
                "source_location_id": source_lane[1],
                "destination_system_id": destination_system,
                "destination_location_id": destination_lane[1],
                "source_region_id": source_region_id,
                "destination_region_id": destination_region_id,
            }
        )

    return sorted(results, key=lambda opportunity: opportunity["net_profit"], reverse=True)[:limit]
