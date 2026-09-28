import math
from datetime import UTC, datetime

from sqlalchemy import and_, select

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


def _group_orders_by_lane(orders):
    lanes = {}
    for order in orders:
        lane = (order.system_id, order.location_id)
        lanes.setdefault(lane, []).append(order)
    return lanes


def _select_candidate_lanes(lanes, *, is_source, max_lanes=8):
    """Keep a bounded set of liquid, price-competitive station lanes."""
    summaries = []
    for lane, orders in lanes.items():
        ordered = sorted(orders, key=lambda o: o.price, reverse=not is_source)
        volume = sum(o.volume_remain for o in orders)
        if volume <= 0:
            continue
        summaries.append((lane, ordered, volume))

    summaries.sort(
        key=lambda x: (x[1][0].price, -x[2])
        if is_source
        else (-x[1][0].price, -x[2])
    )
    return summaries[:max_lanes]


def _route_for_lane(route_client, route_cache, origin, destination, preference, security_penalty):
    cache_key = (origin, destination, preference, security_penalty)
    if cache_key in route_cache:
        return route_cache[cache_key]

    if not route_client or origin == destination:
        route_cache[cache_key] = ([origin], 0)
        return route_cache[cache_key]

    route = route_client.route(
        origin,
        destination,
        preference=preference,
        security_penalty=security_penalty,
    )
    route_cache[cache_key] = (route, max(0, len(route) - 1))
    return route_cache[cache_key]


def _max_affordable_quantity(
    source_orders,
    destination_orders,
    max_quantity,
    capital_isk,
    volume_m3,
    cargo_m3,
    jumps,
    costs,
) -> int:
    """Find the largest executable quantity within the configured cash requirement.

    The scanner is intentionally conservative: capital must cover the purchase
    plus all modeled trade costs. This prevents transport and safety-margin
    assumptions from being ignored when sizing a trade.
    """
    max_quantity = min(max_quantity, math.floor(cargo_m3 / volume_m3 + 1e-9))
    if max_quantity <= 0:
        return 0

    def affordable(quantity):
        acquired, spent = _consume_orders(source_orders, quantity)
        sold, revenue = _sell_orders(destination_orders, quantity)
        if acquired != quantity or sold != quantity:
            return False
        trade_costs = calculate_trade_costs(
            revenue, quantity * volume_m3, jumps, costs
        )
        required_capital = spent + trade_costs["total_costs"]
        return required_capital <= capital_isk

    low, high = 0, max_quantity
    while low < high:
        mid = (low + high + 1) // 2
        if affordable(mid):
            low = mid
        else:
            high = mid - 1
    return low


def _liquidity_class(quantity: int, book_capacity: int, coverage: float) -> str:
    """Classify executable depth using absolute quantity and book consumption."""
    if quantity <= 1:
        return "Muito baixa"
    if quantity >= 1000 and book_capacity >= 1000 and coverage <= 0.50:
        return "Alta"
    if quantity >= 100 and book_capacity >= 100 and coverage <= 0.80:
        return "Média"
    return "Baixa"

def _execution_class(quantity: int, book_capacity: int, coverage: float) -> str:
    """Classify execution scale using depth rather than ROI alone."""
    if quantity <= 2 or book_capacity <= 2:
        return "Especulativa"
    if quantity >= 100 and book_capacity >= 100 and coverage <= 0.80:
        return "Escalável"
    return "Executável"



def find_opportunities(
    session,
    source_region_id,
    destination_region_id,
    capital_isk,
    cargo_m3,
    min_roi=0.05,
    min_profit_isk=100_000,
    limit=100,
    costs=None,
    route_client=None,
    route_preference="Shorter",
    security_penalty=50,
    risk_profile=None,
    execution_profile=None,
    diagnostics=None,
    sort_by="net_profit",
    max_candidate_lanes=4,
    max_market_age_minutes=60.0,
):
    """Find cross-region opportunities across multiple station lanes."""
    costs = costs or TradeCosts()
    costs.validate()
    risk_profile = risk_profile or RiskProfile()
    risk_profile.validate()
    execution_profile = execution_profile or ExecutionProfile()

    allowed_sort_keys = {"net_profit", "roi", "isk_per_hour", "capital_efficiency"}
    if sort_by not in allowed_sort_keys:
        raise ValueError(f"unsupported sort_by: {sort_by}")
    if max_candidate_lanes < 1:
        raise ValueError("max_candidate_lanes must be positive")
    if max_market_age_minutes < 0:
        raise ValueError("max_market_age_minutes must be non-negative")

    item_ids = session.execute(
        select(MarketOrder.type_id)
        .where(MarketOrder.region_id.in_([source_region_id, destination_region_id]))
        .distinct()
    ).scalars().all()

    results = []
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update({
            "market_types": len(item_ids),
            "with_source_orders": 0, "with_destination_orders": 0,
            "with_both_sides": 0, "with_valid_volume": 0,
            "routes_checked": 0, "routes_allowed": 0,
            "rejected_max_jumps": 0, "rejected_nullsec": 0,
            "rejected_lowsec": 0, "rejected_unknown_route": 0,
            "rejected_other_risk": 0, "route_empty": 0,
            "route_systems_missing": 0, "route_systems_found": 0,
            "route_shape_invalid": 0, "quantity_executable": 0,
            "gross_profit_positive": 0, "roi_pass": 0,
            "profit_pass": 0, "final_opportunities": 0,
            "candidate_pairs": 0,
            "rejected_before_route": 0,
            "rejected_capital": 0,
            "rejected_stale_market": 0,
        })

    route_cache = {}
    system_cache = {}
    for type_id in item_ids:
        item = session.get(Item, type_id)
        source_orders = session.scalars(select(MarketOrder).where(and_(
            MarketOrder.region_id == source_region_id,
            MarketOrder.type_id == type_id,
            MarketOrder.is_buy_order.is_(False),
            MarketOrder.volume_remain > 0,
        )).order_by(MarketOrder.price.asc())).all()
        destination_orders = session.scalars(select(MarketOrder).where(and_(
            MarketOrder.region_id == destination_region_id,
            MarketOrder.type_id == type_id,
            MarketOrder.is_buy_order.is_(True),
            MarketOrder.volume_remain > 0,
        )).order_by(MarketOrder.price.desc())).all()

        if source_orders and diagnostics is not None:
            diagnostics["with_source_orders"] += 1
        if destination_orders and diagnostics is not None:
            diagnostics["with_destination_orders"] += 1
        if not source_orders or not destination_orders:
            continue
        if diagnostics is not None:
            diagnostics["with_both_sides"] += 1

        volume = item.volume if item else 0.0
        if volume <= 0 or cargo_m3 <= 0 or capital_isk <= 0:
            continue
        if diagnostics is not None:
            diagnostics["with_valid_volume"] += 1

        source_lanes = _select_candidate_lanes(
            _group_orders_by_lane(source_orders), is_source=True, max_lanes=max_candidate_lanes
        )
        destination_lanes = _select_candidate_lanes(
            _group_orders_by_lane(destination_orders), is_source=False, max_lanes=max_candidate_lanes
        )

        for source_lane, source_book, source_book_volume in source_lanes:
            for destination_lane, destination_book, destination_book_volume in destination_lanes:
                if diagnostics is not None:
                    diagnostics["candidate_pairs"] += 1

                origin_system, origin_location = source_lane
                destination_system, destination_location = destination_lane

                collected_times = [
                    order.collected_at
                    for order in (*source_book, *destination_book)
                    if order.collected_at is not None
                ]
                market_age_minutes = None
                if collected_times:
                    now = datetime.now(UTC).replace(tzinfo=None)
                    oldest_snapshot = min(collected_times)
                    market_age_minutes = max(
                        0.0, (now - oldest_snapshot).total_seconds() / 60.0
                    )
                    if market_age_minutes > max_market_age_minutes:
                        if diagnostics is not None:
                            diagnostics["rejected_stale_market"] += 1
                        continue

                # Use an optimistic price-only ROI bound before calling ESI.
                best_buy = source_book[0].price
                best_sell = destination_book[0].price
                optimistic_net = (
                    best_sell
                    - best_buy
                    - best_sell * costs.sales_tax_rate
                    - best_sell * costs.broker_fee_rate
                )
                optimistic_roi = optimistic_net / best_buy if best_buy > 0 else 0.0
                if optimistic_roi < min_roi:
                    if diagnostics is not None:
                        diagnostics["rejected_before_route"] += 1
                    continue

                route, jumps = _route_for_lane(
                    route_client, route_cache, origin_system, destination_system,
                    route_preference, security_penalty
                )

                if diagnostics is not None:
                    diagnostics["routes_checked"] += 1
                if not isinstance(route, list) or not all(isinstance(x, int) for x in route):
                    if diagnostics is not None:
                        diagnostics["route_shape_invalid"] += 1
                    continue
                if not route:
                    if diagnostics is not None:
                        diagnostics["route_empty"] += 1
                    continue

                systems = []
                for system_id in route:
                    if system_id not in system_cache:
                        system_cache[system_id] = session.get(SolarSystem, system_id)
                    if system_cache[system_id] is not None:
                        systems.append(system_cache[system_id])
                if diagnostics is not None:
                    diagnostics["route_systems_found"] += len(systems)
                    diagnostics["route_systems_missing"] += len(route) - len(systems)

                risk = analyze_route(systems, jumps)
                risk["jumps"] = jumps
                if not route_allowed(risk_profile, risk):
                    if diagnostics is not None:
                        if risk_profile.max_jumps is not None and jumps > risk_profile.max_jumps:
                            diagnostics["rejected_max_jumps"] += 1
                        elif risk.get("nullsec_systems", 0) > 0 and not risk_profile.allow_nullsec:
                            diagnostics["rejected_nullsec"] += 1
                        elif risk.get("lowsec_systems", 0) > 0 and not risk_profile.allow_lowsec:
                            diagnostics["rejected_lowsec"] += 1
                        elif risk.get("route_class") == "unknown":
                            diagnostics["rejected_unknown_route"] += 1
                        else:
                            diagnostics["rejected_other_risk"] += 1
                    continue
                if diagnostics is not None:
                    diagnostics["routes_allowed"] += 1

                max_quantity = min(
                    source_book_volume, destination_book_volume,
                    math.floor(cargo_m3 / volume + 1e-9),
                )
                quantity = _max_affordable_quantity(
                    source_book, destination_book, max_quantity,
                    capital_isk, volume, cargo_m3, jumps, costs,
                )
                if quantity <= 0:
                    if diagnostics is not None:
                        diagnostics["rejected_capital"] += 1
                    continue
                if diagnostics is not None:
                    diagnostics["quantity_executable"] += 1

                _, spent = _consume_orders(source_book, quantity)
                _, revenue = _sell_orders(destination_book, quantity)
                trade_costs = calculate_trade_costs(
                    revenue, quantity * volume, jumps, costs
                )
                gross_profit = revenue - spent
                net_profit = gross_profit - trade_costs["total_costs"]
                roi = net_profit / spent if spent else 0.0
                estimated_minutes = (
                    execution_profile.fixed_minutes
                    + jumps * execution_profile.minutes_per_jump
                )
                if execution_profile.return_trip:
                    estimated_minutes *= 2
                isk_per_hour = estimate_isk_per_hour(net_profit, jumps, execution_profile)
                capital_efficiency = net_profit / spent if spent else 0.0
                avg_buy = spent / quantity
                avg_sell = revenue / quantity
                spread_isk = avg_sell - avg_buy
                spread_pct = spread_isk / avg_buy if avg_buy else 0.0
                book_capacity = min(source_book_volume, destination_book_volume)
                book_coverage = quantity / book_capacity if book_capacity else 0.0
                liquidity_class = _liquidity_class(
                    quantity, book_capacity, book_coverage
                )
                execution_class = _execution_class(
                    quantity, book_capacity, book_coverage
                )

                if gross_profit > 0 and diagnostics is not None:
                    diagnostics["gross_profit_positive"] += 1
                if roi < min_roi:
                    continue
                if diagnostics is not None:
                    diagnostics["roi_pass"] += 1
                if net_profit < min_profit_isk:
                    continue
                if diagnostics is not None:
                    diagnostics["profit_pass"] += 1

                results.append({
                    "type_id": type_id, "name": item.name if item else f"type:{type_id}",
                    "quantity": quantity, "buy_cost": spent, "sell_revenue": revenue,
                    "avg_buy_price": avg_buy, "avg_sell_price": avg_sell,
                    "gross_profit": gross_profit,
                    "sales_tax": trade_costs["sales_tax"],
                    "broker_fee": trade_costs["broker_fee"],
                    "transport_cost": trade_costs["transport_cost"],
                    "safety_margin": trade_costs["safety_margin"],
                    "total_costs": trade_costs["total_costs"],
                    "net_profit": net_profit, "roi": roi,
                    "profit_per_unit": net_profit / quantity if quantity else 0.0,
                    "capital_required": spent + trade_costs["total_costs"],
                    "capital_efficiency": capital_efficiency,
                    "spread_isk": spread_isk, "spread_pct": spread_pct,
                    "source_book_volume": source_book_volume,
                    "destination_book_volume": destination_book_volume,
                    "book_capacity": book_capacity,
                    "book_coverage": book_coverage,
                    "liquidity_class": liquidity_class,
                    "execution_class": execution_class,
                    "scalable": execution_class == "Escalável",
                    "min_executable_quantity": quantity,
                    "market_age_minutes": market_age_minutes,
                    "estimated_minutes": estimated_minutes, "isk_per_hour": isk_per_hour,
                    "volume_m3": quantity * volume, "jumps": jumps,
                    "route_system_ids": route, "route_class": risk["route_class"],
                    "highsec_systems": risk["highsec_systems"],
                    "lowsec_systems": risk["lowsec_systems"],
                    "nullsec_systems": risk["nullsec_systems"],
                    "min_security_status": risk["min_security_status"],
                    "risk_score": risk["risk_score"],
                    "source_system_id": origin_system,
                    "source_system_name": systems[0].name if systems else f"system:{origin_system}",
                    "source_location_id": origin_location,
                    "destination_system_id": destination_system,
                    "destination_system_name": next(
                        (system.name for system in systems if system.system_id == destination_system),
                        f"system:{destination_system}",
                    ),
                    "destination_location_id": destination_location,
                    "source_region_id": source_region_id,
                    "destination_region_id": destination_region_id,
                })

    results = sorted(results, key=lambda x: x["capital_efficiency"] if sort_by == "capital_efficiency" else x[sort_by], reverse=True)[:limit]
    if diagnostics is not None:
        diagnostics["final_opportunities"] = len(results)
    return results
