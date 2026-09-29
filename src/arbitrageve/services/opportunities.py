import math
from datetime import UTC, datetime

from sqlalchemy import and_, case, func, select

from arbitrageve.db.models import Item, MarketOrder, SolarSystem
from arbitrageve.market.costs import TradeCosts, calculate_trade_costs
from arbitrageve.market.execution import simulate_order_book_execution
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



def calculate_operational_score(opportunity: dict) -> dict[str, float]:
    execution_points = {'Escalável': 100.0, 'Executável': 70.0, 'Especulativa': 30.0}
    liquidity_points = {'Alta': 100.0, 'Média': 75.0, 'Baixa': 45.0, 'Muito baixa': 15.0}
    execution = execution_points.get(opportunity.get('execution_class'), 50.0)
    liquidity = liquidity_points.get(opportunity.get('liquidity_class'), 40.0)
    roi = max(0.0, min(float(opportunity.get('roi', 0.0)) / 0.50, 1.0)) * 100.0
    isk_hour = max(0.0, min(float(opportunity.get('isk_per_hour', 0.0)) / 10000000, 1.0)) * 100.0
    coverage = max(0.0, min(float(opportunity.get('book_coverage', 1.0)), 1.0))
    depth = (1.0 - coverage) * 100.0
    risk = max(0.0, min(float(opportunity.get('risk_score', 0.0)), 1.0))
    route = max(0.0, min(1.0 - risk, 1.0)) * 100.0
    score = execution * 0.25 + liquidity * 0.20 + roi * 0.15 + isk_hour * 0.20 + depth * 0.10 + route * 0.10
    return {'operational_score': round(score, 2), 'score_execution': round(execution, 2), 'score_liquidity': round(liquidity, 2), 'score_roi': round(roi, 2), 'score_isk_hour': round(isk_hour, 2), 'score_depth': round(depth, 2), 'score_route': round(route, 2)}

def audit_opportunity_execution(
    opportunity: dict,
    *,
    capital_isk: float,
    cargo_m3: float,
    max_market_age_minutes: float | None = 60.0,
) -> dict:
    """Audit whether an already-calculated opportunity is internally executable.

    This is deliberately separate from ranking. It validates the arithmetic and
    hard constraints that must hold before a displayed profit is treated as
    executable: capital, cargo, both books, modeled costs, route completeness,
    market freshness, and the level-by-level execution quantities.
    """
    quantity = int(opportunity.get("quantity", 0))
    buy_cost = float(opportunity.get("buy_cost", 0.0))
    revenue = float(opportunity.get("sell_revenue", 0.0))
    total_costs = float(opportunity.get("total_costs", 0.0))
    net_profit = float(opportunity.get("net_profit", 0.0))
    capital_required = float(opportunity.get("capital_required", buy_cost + total_costs))
    volume_m3 = float(opportunity.get("volume_m3", 0.0))
    source_book = int(opportunity.get("source_book_volume", 0))
    destination_book = int(opportunity.get("destination_book_volume", 0))
    route = opportunity.get("route_system_ids") or []
    jumps = int(opportunity.get("jumps", 0))
    market_age = opportunity.get("market_age_minutes")

    issues: list[str] = []

    capital_ok = capital_required <= float(capital_isk) + 1e-9
    cargo_ok = volume_m3 <= float(cargo_m3) + 1e-9
    book_ok = (
        quantity > 0
        and quantity <= source_book
        and quantity <= destination_book
    )

    arithmetic_ok = (
        buy_cost >= 0
        and revenue >= 0
        and total_costs >= 0
        and abs((revenue - buy_cost - total_costs) - net_profit) <= 1e-6
    )

    buy_levels = opportunity.get("buy_levels") or []
    sell_levels = opportunity.get("sell_levels") or []
    buy_level_quantity = sum(int(level.get("quantity", 0)) for level in buy_levels)
    sell_level_quantity = sum(int(level.get("quantity", 0)) for level in sell_levels)
    levels_ok = (
        buy_level_quantity == quantity
        and sell_level_quantity == quantity
        and all(int(level.get("quantity", 0)) > 0 for level in (*buy_levels, *sell_levels))
    )

    route_ok = (
        bool(opportunity.get("route_known", False))
        and bool(route)
        and all(isinstance(system_id, int) for system_id in route)
        and len(route) == jumps + 1
        and opportunity.get("route_class") in {"highsec", "lowsec", "nullsec"}
    )

    freshness_ok = (
        max_market_age_minutes is None
        or market_age is not None and float(market_age) <= max_market_age_minutes + 1e-9
    )

    profit_ok = net_profit >= 0
    for name, ok in (
        ("capital", capital_ok),
        ("cargo", cargo_ok),
        ("order_book", book_ok),
        ("arithmetic", arithmetic_ok),
        ("execution_levels", levels_ok),
        ("route", route_ok),
        ("market_freshness", freshness_ok),
        ("profit", profit_ok),
    ):
        if not ok:
            issues.append(name)

    capital_headroom = float(capital_isk) - capital_required
    cargo_headroom = float(cargo_m3) - volume_m3
    book_headroom = min(source_book, destination_book) - quantity
    cost_ratio = total_costs / buy_cost if buy_cost > 0 else 0.0

    return {
        "execution_verified": not issues,
        "execution_audit_issues": issues,
        "capital_ok": capital_ok,
        "cargo_ok": cargo_ok,
        "book_ok": book_ok,
        "arithmetic_ok": arithmetic_ok,
        "execution_levels_ok": levels_ok,
        "route_ok": route_ok,
        "market_freshness_ok": freshness_ok,
        "profit_ok": profit_ok,
        "capital_headroom": capital_headroom,
        "cargo_headroom_m3": cargo_headroom,
        "book_headroom": book_headroom,
        "cost_ratio": cost_ratio,
        "capital_efficiency_equals_roi": abs(
            float(opportunity.get("capital_efficiency", 0.0))
            - float(opportunity.get("roi", 0.0))
        ) <= 1e-12,
    }

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
    type_ids=None,
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

    item_query = select(MarketOrder.type_id).where(
        MarketOrder.region_id.in_([source_region_id, destination_region_id])
    )
    if type_ids is not None:
        type_ids = {int(type_id) for type_id in type_ids}
        item_query = item_query.where(MarketOrder.type_id.in_(type_ids))
    item_ids = session.execute(item_query.distinct()).scalars().all()

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
                missing_systems = len(route) - len(systems)
                if diagnostics is not None:
                    diagnostics["route_systems_found"] += len(systems)
                    diagnostics["route_systems_missing"] += missing_systems

                # A partial route cannot support a trustworthy security audit.
                # Reject it rather than silently classifying only the systems
                # that happened to be present in the database.
                if missing_systems:
                    if diagnostics is not None:
                        diagnostics["rejected_unknown_route"] += 1
                    continue

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

                execution = simulate_order_book_execution(
                    source_book,
                    destination_book,
                    quantity,
                    volume,
                    jumps,
                    costs,
                )
                spent = execution["buy_cost"]
                revenue = execution["sell_revenue"]
                trade_costs = {
                    "sales_tax": execution["sales_tax"],
                    "broker_fee": execution["broker_fee"],
                    "transport_cost": execution["transport_cost"],
                    "safety_margin": execution["safety_margin"],
                    "total_costs": execution["total_costs"],
                }
                gross_profit = execution["gross_profit"]
                net_profit = execution["net_profit"]
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
                    "buy_levels": execution["buy_levels"],
                    "sell_levels": execution["sell_levels"],
                    "buy_levels_used": execution["buy_levels_used"],
                    "sell_levels_used": execution["sell_levels_used"],
                    "buy_marginal_price": execution["buy_marginal_price"],
                    "sell_marginal_price": execution["sell_marginal_price"],
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
                results[-1].update(calculate_operational_score(results[-1]))
                results[-1].update(
                    audit_opportunity_execution(
                        results[-1],
                        capital_isk=capital_isk,
                        cargo_m3=cargo_m3,
                        max_market_age_minutes=max_market_age_minutes,
                    )
                )

    results = sorted(results, key=lambda x: x["capital_efficiency"] if sort_by == "capital_efficiency" else x[sort_by], reverse=True)[:limit]
    if diagnostics is not None:
        diagnostics["final_opportunities"] = len(results)
    return results


def discover_global_candidates(
    session,
    *,
    min_roi: float = 0.05,
    min_profit_isk: float = 100_000,
    capital_isk: float | None = None,
    cargo_m3: float | None = None,
    max_market_age_minutes: float | None = 60.0,
    costs: TradeCosts | None = None,
    max_candidates: int = 200,
) -> list[dict]:
    """Discover cross-region candidates with SQL-first cheap filters."""
    costs = costs or TradeCosts()
    costs.validate()
    if min_roi < 0:
        raise ValueError("min_roi must be non-negative")
    if min_profit_isk < 0:
        raise ValueError("min_profit_isk must be non-negative")
    if capital_isk is not None and capital_isk < 0:
        raise ValueError("capital_isk cannot be negative")
    if cargo_m3 is not None and cargo_m3 < 0:
        raise ValueError("cargo_m3 cannot be negative")
    if max_market_age_minutes is not None and max_market_age_minutes < 0:
        raise ValueError("max_market_age_minutes cannot be negative")
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive")

    now = datetime.now(UTC).replace(tzinfo=None)
    cutoff = (
        now.timestamp() - max_market_age_minutes * 60
        if max_market_age_minutes is not None
        else None
    )

    sells = (
        select(
            MarketOrder.region_id.label("source_region_id"),
            MarketOrder.type_id.label("type_id"),
            func.min(MarketOrder.price).label("buy_price"),
            func.sum(MarketOrder.volume_remain).label("source_volume"),
            func.min(MarketOrder.collected_at).label("source_oldest"),
        )
        .where(
            MarketOrder.is_buy_order.is_(False),
            MarketOrder.volume_remain > 0,
        )
        .group_by(MarketOrder.region_id, MarketOrder.type_id)
        .subquery()
    )
    buys = (
        select(
            MarketOrder.region_id.label("destination_region_id"),
            MarketOrder.type_id.label("type_id"),
            func.max(MarketOrder.price).label("sell_price"),
            func.sum(MarketOrder.volume_remain).label("destination_volume"),
            func.min(MarketOrder.collected_at).label("destination_oldest"),
        )
        .where(
            MarketOrder.is_buy_order.is_(True),
            MarketOrder.volume_remain > 0,
        )
        .group_by(MarketOrder.region_id, MarketOrder.type_id)
        .subquery()
    )

    buy_price = sells.c.buy_price
    sell_price = buys.c.sell_price
    net_per_unit = sell_price * (
        1 - costs.sales_tax_rate - costs.broker_fee_rate
    )
    book_quantity = case(
        (sells.c.source_volume < buys.c.destination_volume, sells.c.source_volume),
        else_=buys.c.destination_volume,
    )
    optimistic_book_profit = (net_per_unit - buy_price) * book_quantity
    optimistic_roi = (net_per_unit - buy_price) / buy_price

    conditions = [
        buy_price > 0,
        sell_price > buy_price,
        Item.volume > 0,
        optimistic_roi >= min_roi,
        optimistic_book_profit >= min_profit_isk,
    ]
    if capital_isk is not None:
        conditions.append(buy_price <= capital_isk)

    if max_market_age_minutes is not None:
        cutoff_dt = datetime.fromtimestamp(cutoff, UTC).replace(tzinfo=None)
        conditions.extend(
            [
                sells.c.source_oldest >= cutoff_dt,
                buys.c.destination_oldest >= cutoff_dt,
            ]
        )

    stmt = (
        select(
            sells.c.type_id,
            sells.c.source_region_id,
            buys.c.destination_region_id,
            sells.c.buy_price,
            buys.c.sell_price,
            sells.c.source_volume,
            buys.c.destination_volume,
            sells.c.source_oldest,
            buys.c.destination_oldest,
            Item.volume.label("volume"),
        )
        .select_from(
            sells.join(
                buys,
                and_(
                    buys.c.type_id == sells.c.type_id,
                    buys.c.destination_region_id != sells.c.source_region_id,
                ),
            ).join(Item, Item.type_id == sells.c.type_id)
        )
        .where(*conditions)
        .order_by(
            optimistic_book_profit.desc(),
            optimistic_roi.desc(),
            (sell_price - buy_price).desc(),
        )
        .limit(max_candidates * 4)
    )

    rows = session.execute(stmt).mappings().all()
    candidates = []

    for row in rows:
        if max_market_age_minutes is not None:
            oldest = min(
                timestamp
                for timestamp in (
                    row["source_oldest"],
                    row["destination_oldest"],
                )
                if timestamp is not None
            )
            age_minutes = max(0.0, (now - oldest).total_seconds() / 60.0)
        else:
            age_minutes = None

        volume = float(row["volume"])
        max_by_book = min(row["source_volume"], row["destination_volume"])
        max_by_cargo = (
            math.floor(cargo_m3 / volume + 1e-9)
            if cargo_m3 is not None and cargo_m3 > 0
            else max_by_book
        )
        max_quantity = min(max_by_book, max_by_cargo)
        if max_quantity <= 0:
            continue

        buy_price_value = float(row["buy_price"])
        sell_price_value = float(row["sell_price"])
        net_per_unit_value = (
            sell_price_value
            * (1 - costs.sales_tax_rate - costs.broker_fee_rate)
            - buy_price_value
        )
        optimistic_roi_value = (
            net_per_unit_value / buy_price_value
            if buy_price_value > 0
            else 0.0
        )
        optimistic_profit = net_per_unit_value * max_quantity

        if (
            optimistic_roi_value < min_roi
            or optimistic_profit < min_profit_isk
        ):
            continue

        if capital_isk is not None and buy_price_value * max_quantity > capital_isk:
            max_quantity = min(
                max_quantity,
                math.floor(capital_isk / buy_price_value),
            )
            optimistic_profit = net_per_unit_value * max_quantity
            if max_quantity <= 0 or optimistic_profit < min_profit_isk:
                continue

        candidates.append(
            {
                "type_id": row["type_id"],
                "source_region_id": row["source_region_id"],
                "destination_region_id": row["destination_region_id"],
                "buy_price": buy_price_value,
                "sell_price": sell_price_value,
                "source_volume": row["source_volume"],
                "destination_volume": row["destination_volume"],
                "spread_isk": sell_price_value - buy_price_value,
                "optimistic_roi": optimistic_roi_value,
                "optimistic_profit": optimistic_profit,
                "max_quantity_bound": int(max_quantity),
                "market_age_minutes": age_minutes,
            }
        )

    candidates.sort(
        key=lambda row: (
            row["optimistic_profit"],
            row["optimistic_roi"],
            row["spread_isk"],
        ),
        reverse=True,
    )
    return candidates[:max_candidates]


def _deduplicate_opportunities(results, *, sort_by="net_profit"):
    """Keep the best execution for each economic system-to-system lane."""
    if not results:
        return []

    def sort_key(row):
        return row.get(sort_by, row.get("net_profit", 0))

    best_by_lane = {}
    for row in results:
        key = (
            row.get("type_id"),
            row.get("source_system_id"),
            row.get("destination_system_id"),
        )
        current = best_by_lane.get(key)
        if current is None or sort_key(row) > sort_key(current):
            best_by_lane[key] = row

    return list(best_by_lane.values())

def find_global_opportunities(
    session,
    capital_isk,
    cargo_m3,
    *,
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
    max_candidates=200,
):
    """Find executable arbitrage across the loaded market universe."""
    costs = costs or TradeCosts()
    candidates = discover_global_candidates(
        session,
        min_roi=min_roi,
        costs=costs,
        min_profit_isk=min_profit_isk,
        capital_isk=capital_isk,
        cargo_m3=cargo_m3,
        max_market_age_minutes=max_market_age_minutes,
        max_candidates=max_candidates,
    )
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update({
            "global_candidates": len(candidates),
            "candidate_region_pairs": len({
                (row["source_region_id"], row["destination_region_id"])
                for row in candidates
            }),
            "detailed_scans": 0,
            "final_opportunities": 0,
        })

    results = []
    for candidate in candidates:
        detailed = find_opportunities(
            session,
            candidate["source_region_id"],
            candidate["destination_region_id"],
            capital_isk,
            cargo_m3,
            min_roi=min_roi,
            min_profit_isk=min_profit_isk,
            limit=limit,
            costs=costs,
            route_client=route_client,
            route_preference=route_preference,
            security_penalty=security_penalty,
            risk_profile=risk_profile,
            execution_profile=execution_profile,
            sort_by=sort_by,
            max_candidate_lanes=max_candidate_lanes,
            max_market_age_minutes=max_market_age_minutes,
            type_ids={candidate["type_id"]},
        )
        if diagnostics is not None:
            diagnostics["detailed_scans"] += 1
        results.extend(detailed)

    before_dedup = len(results)
    results = _deduplicate_opportunities(results, sort_by=sort_by)
    results.sort(
        key=lambda row: row.get(sort_by, row.get("net_profit", 0)),
        reverse=True,
    )
    if diagnostics is not None:
        diagnostics["opportunities_before_dedup"] = before_dedup
        diagnostics["duplicates_removed"] = before_dedup - len(results)
        diagnostics["final_opportunities"] = min(len(results), limit)
    return results[:limit]
