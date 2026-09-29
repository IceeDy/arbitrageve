import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime import load_repo_module

load_repo_module("arbitrageve.db.database", "arbitrageve/db/database.py")
load_repo_module("arbitrageve.db.models", "arbitrageve/db/models.py")
load_repo_module("arbitrageve.sde.loader", "arbitrageve/sde/loader.py")

import streamlit as st
from theme import apply_eve_theme, render_topbar

from arbitrageve.config.regions import REGIONS
from arbitrageve.config.settings import settings
from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.db.models import Region, SolarSystem, Stargate
from arbitrageve.market.costs import TradeCosts
from arbitrageve.market.metrics import ExecutionProfile
from arbitrageve.sde.routes import LocalRouteClient
from arbitrageve.services.opportunities import (
    find_global_opportunities,
    find_opportunities,
)
from arbitrageve.services.risk import RiskProfile

st.set_page_config(page_title="ArbitragEVE", page_icon="📈", layout="wide", initial_sidebar_state="expanded")
init_db()
apply_eve_theme()
render_topbar("GLOBAL MARKET SCANNER")

st.caption("Cross-region arbitrage · order-book execution · route-aware returns")

with st.sidebar:
    st.header("Market")
    capital = st.number_input("Capital (ISK)", min_value=0.0, value=settings.capital_isk, step=1_000_000.0)
    cargo = st.number_input("Cargo (m³)", min_value=0.0, value=settings.cargo_m3, step=10.0)
    with SessionLocal() as region_session:
        db_regions = {
            region.region_id: region.name
            for region in region_session.query(Region).order_by(Region.name).all()
        }
    market_regions = db_regions or REGIONS
    region_ids = list(market_regions)
    scan_scope = st.radio(
        "Escopo do scanner",
        ["Universo inteiro", "Entre regiões"],
        horizontal=True,
        help="Universo inteiro faz uma descoberta global limitada antes da análise detalhada.",
    )
    source = destination = None
    if scan_scope == "Entre regiões":
        source = st.selectbox(
            "Comprar em",
            options=region_ids,
            format_func=lambda region_id: market_regions[region_id],
        )
        destination_options = [region_id for region_id in region_ids if region_id != source]
        destination = st.selectbox(
            "Vender em",
            options=destination_options,
            format_func=lambda region_id: market_regions[region_id],
        )
    else:
        max_global_candidates = st.number_input(
            "Candidatos globais detalhados",
            min_value=10,
            max_value=2000,
            value=200,
            step=10,
            help="Limita quantos pares item/região entram na análise pesada de order book e rota.",
        )
    min_roi = st.slider("ROI líquido mínimo", 0.0, 1.0, 0.05, 0.01)
    min_profit = st.number_input("Lucro líquido mínimo", min_value=0.0, value=100_000.0, step=100_000.0)
    max_market_age = st.number_input("Snapshot máximo (min)", min_value=0.0, value=60.0, step=5.0)

    st.divider()
    st.subheader("Execution filters")
    min_quantity = st.number_input("Quantidade mínima", min_value=1, value=1, step=1)
    min_profit_unit = st.number_input("Lucro/unid. mínimo", min_value=0.0, value=0.0, step=100.0)
    max_capital = st.number_input("Capital máximo por operação", min_value=0.0, value=0.0, step=1_000_000.0, help="0 = sem limite")
    require_scalable = st.checkbox("Somente operações escaláveis", value=False)

    st.divider()
    st.subheader("Route")
    route_preference = st.selectbox(
        "Preferência",
        ["Shorter", "Safer", "LessSecure"],
        format_func=lambda value: {"Shorter": "Mais curta", "Safer": "Mais segura", "LessSecure": "Menos segura"}[value],
    )
    security_penalty = st.slider("Penalidade de segurança", 0, 100, 50, 5)
    allow_lowsec = st.checkbox("Permitir low-sec", value=True)
    allow_nullsec = st.checkbox("Permitir null-sec", value=False)
    max_jumps = st.number_input("Máximo de jumps", min_value=0, value=30, step=1)

    st.divider()
    st.subheader("Timing")
    fixed_minutes = st.number_input("Tempo fixo por operação (min)", min_value=0.0, value=10.0, step=1.0)
    minutes_per_jump = st.number_input("Tempo por jump (min)", min_value=0.0, value=2.0, step=0.5)
    return_trip = st.checkbox("Considerar viagem de retorno", value=False)
    execution_filter = st.multiselect(
        "Classe de execução",
        ["Escalável", "Executável", "Especulativa"],
        default=["Escalável", "Executável", "Especulativa"],
        help="Filtra operações pela capacidade de execução calculada a partir da quantidade e profundidade do book.",
    )
    sort_by = st.selectbox(
        "Ordenar por",
        ["isk_per_hour", "net_profit", "roi", "capital_efficiency"],
        format_func=lambda value: {
            "isk_per_hour": "ISK/h estimado",
            "net_profit": "Lucro líquido",
            "roi": "ROI líquido",
            "capital_efficiency": "Eficiência do capital",
        }[value],
    )

    st.divider()
    st.subheader("Costs")
    sales_tax = st.number_input("Sales tax (%)", min_value=0.0, max_value=100.0, value=7.5, step=0.1) / 100
    broker_fee = st.number_input("Broker fee (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.1) / 100
    transport_flat = st.number_input("Transporte por viagem (ISK)", min_value=0.0, value=0.0, step=10_000.0)
    transport_m3_jump = st.number_input("Transporte (ISK/m³/jump)", min_value=0.0, value=0.0, step=10.0)
    safety_margin = st.number_input("Margem de segurança sobre custos (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.5) / 100

if scan_scope == "Entre regiões" and source == destination:
    st.warning("Escolha regiões diferentes.")
else:
    costs = TradeCosts(
        sales_tax_rate=sales_tax,
        broker_fee_rate=broker_fee,
        transport_flat_isk=transport_flat,
        transport_isk_per_m3_jump=transport_m3_jump,
        safety_margin_rate=safety_margin,
    )
    risk_profile = RiskProfile(
        allow_highsec=True,
        allow_lowsec=allow_lowsec,
        allow_nullsec=allow_nullsec,
        max_jumps=max_jumps,
    )
    execution_profile = ExecutionProfile(
        fixed_minutes=fixed_minutes,
        minutes_per_jump=minutes_per_jump,
        return_trip=return_trip,
    )

    diagnostics = {}
    with SessionLocal() as session:
        stargate_count = session.query(Stargate).count()
        if stargate_count == 0:
            st.error(
                "O grafo local de rotas está vazio. Vá em Dados → Atualizar SDE "
                "para importar os stargates antes de executar o scanner."
            )
            st.stop()

        route_client = LocalRouteClient(session)
        if scan_scope == "Universo inteiro":
            opportunities = find_global_opportunities(
                session,
                capital,
                cargo,
                min_roi=min_roi,
                min_profit_isk=min_profit,
                costs=costs,
                route_client=route_client,
                route_preference=route_preference,
                security_penalty=security_penalty,
                risk_profile=risk_profile,
                execution_profile=execution_profile,
                diagnostics=diagnostics,
                sort_by=sort_by,
                max_market_age_minutes=max_market_age,
                max_candidates=max_global_candidates,
            )
        else:
            opportunities = find_opportunities(
                session,
                source,
                destination,
                capital,
                cargo,
                min_roi,
                min_profit,
                costs=costs,
                route_client=route_client,
                route_preference=route_preference,
                security_penalty=security_penalty,
                risk_profile=risk_profile,
                execution_profile=execution_profile,
                diagnostics=diagnostics,
                sort_by=sort_by,
                max_market_age_minutes=max_market_age,
            )

    if not opportunities:
        st.info("Nenhuma oportunidade encontrada.")
        with st.expander("🔎 Diagnóstico do scanner", expanded=True):
            st.write("As etapas abaixo mostram onde as oportunidades estão sendo eliminadas.")
            labels = {
                "market_types": "Tipos de mercado analisados",
                "candidate_pairs": "Pares de estações avaliados",
                "with_source_orders": "Com ordem de venda na origem",
                "with_destination_orders": "Com ordem de compra no destino",
                "with_both_sides": "Com os dois lados",
                "with_valid_volume": "Com volume/SDE válidos",
                "routes_checked": "Rotas verificadas",
                "routes_allowed": "Rotas aprovadas pelos filtros",
                "quantity_executable": "Com quantidade executável",
                "gross_profit_positive": "Com lucro bruto positivo",
                "roi_pass": "Acima do ROI mínimo",
                "profit_pass": "Acima do lucro mínimo",
                "final_opportunities": "Oportunidades finais",
                "rejected_before_route": "Descartadas antes da consulta de rota",
            }
            st.dataframe(
                [{"Etapa": label, "Quantidade": diagnostics.get(key, 0)} for key, label in labels.items()]
                + [
                    {"Etapa": "Rejeitadas: máximo de jumps", "Quantidade": diagnostics.get("rejected_max_jumps", 0)},
                    {"Etapa": "Rejeitadas: null-sec", "Quantidade": diagnostics.get("rejected_nullsec", 0)},
                    {"Etapa": "Rejeitadas: low-sec", "Quantidade": diagnostics.get("rejected_lowsec", 0)},
                    {"Etapa": "Rejeitadas: rota desconhecida", "Quantidade": diagnostics.get("rejected_unknown_route", 0)},
                    {"Etapa": "Rejeitadas: outro risco", "Quantidade": diagnostics.get("rejected_other_risk", 0)},
                    {"Etapa": "Rejeitadas: capital insuficiente", "Quantidade": diagnostics.get("rejected_capital", 0)},
                    {"Etapa": "Rejeitadas: snapshot desatualizado", "Quantidade": diagnostics.get("rejected_stale_market", 0)},
                    {"Etapa": "Rotas vazias", "Quantidade": diagnostics.get("route_empty", 0)},
                    {"Etapa": "Rotas com formato inválido", "Quantidade": diagnostics.get("route_shape_invalid", 0)},
                    {"Etapa": "Sistemas de rota encontrados", "Quantidade": diagnostics.get("route_systems_found", 0)},
                    {"Etapa": "Sistemas de rota ausentes no SDE", "Quantidade": diagnostics.get("route_systems_missing", 0)},
                ],
                width="stretch",
                hide_index=True,
            )
    else:
        filtered = [
            item for item in opportunities
            if item.get("execution_class", "Executável") in execution_filter
            and item.get("quantity", 0) >= min_quantity
            and item.get("profit_per_unit", 0.0) >= min_profit_unit
            and (max_capital <= 0 or item.get("capital_required", 0.0) <= max_capital)
            and (not require_scalable or item.get("scalable", False))
        ]
        st.subheader("Market opportunities")
        st.caption(f"{len(filtered)} operações atendem aos filtros atuais · {len(opportunities) - len(filtered)} ocultadas")

        if not filtered:
            st.info("Nenhuma oportunidade corresponde ao filtro de execução selecionado.")
        else:
            total_required = sum(item["capital_required"] for item in filtered)
            scalable_count = sum(item.get("scalable", False) for item in filtered)
            speculative_count = sum(item.get("execution_class") == "Especulativa" for item in filtered)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Operações", len(filtered))
            c2.metric("Capital total", f"{total_required:,.0f} ISK")
            c3.metric("Escaláveis", scalable_count)
            c4.metric("Especulativas", speculative_count)

            rows = [
                {
                    "Item": item["name"],
                    "Execução": item.get("execution_class", "Executável"),
                    "Rota": item["route_class"],
                    "Origem": f'{item["source_system_name"]} (loc {item["source_location_id"]})',
                    "Destino": f'{item["destination_system_name"]} (loc {item["destination_location_id"]})',
                    "Qtd": item["quantity"],
                    "Lucro/unid.": item.get("profit_per_unit", 0.0),
                    "Capital necessário": item.get("capital_required", 0.0),
                    "Compra média": item["avg_buy_price"],
                    "Venda média": item["avg_sell_price"],
                    "Investido": item["buy_cost"],
                    "Lucro líquido": item["net_profit"],
                    "ROI": item["roi"],
                    "ISK/h": item["isk_per_hour"],
                    "Ef. capital": item["capital_efficiency"],
                    "Spread": item["spread_pct"],
                    "Liquidez": item.get("liquidity_class", "Baixa"),
                    "Cobertura book": item["book_coverage"],
                    "Book mínimo": item["book_capacity"],
                    "Jumps": item["jumps"],
                    "Segurança mín.": item["min_security_status"],
                    "Low-sec": item["lowsec_systems"],
                    "Null-sec": item["nullsec_systems"],
                    "m³": item["volume_m3"],
                    "Idade book (min)": item.get("market_age_minutes"),
                }
                for item in filtered
            ]
            st.subheader("Selected opportunity")
            selected_idx = st.selectbox(
                "Selecionar operação",
                options=range(len(filtered)),
                format_func=lambda idx: (
                    f"{filtered[idx]['name']} · "
                    f"{filtered[idx]['net_profit']:,.0f} ISK · "
                    f"{filtered[idx].get('execution_class', 'Executável')}"
                ),
            )
            selected = filtered[selected_idx]

            with st.expander("Abrir detalhes da operação", expanded=True):
                d1, d2, d3, d4 = st.columns(4)
                d1.metric("Lucro líquido", f"{selected['net_profit']:,.0f} ISK")
                d2.metric("ROI", f"{selected['roi']:.2%}")
                d3.metric("Capital", f"{selected['capital_required']:,.0f} ISK")
                d4.metric("ISK/h", f"{selected['isk_per_hour']:,.0f}")

                st.markdown(
                    f"**{selected['name']}** · {selected['quantity']:,} unidades · "
                    f"{selected['volume_m3']:,.1f} m³"
                )
                left, right = st.columns(2)
                with left:
                    st.markdown(
                        f"**Compra:** {selected['avg_buy_price']:,.2f} ISK/unid. "
                        f"em {selected['source_system_name']}"
                    )
                    st.markdown(
                        f"**Venda:** {selected['avg_sell_price']:,.2f} ISK/unid. "
                        f"em {selected['destination_system_name']}"
                    )
                    st.markdown(
                        f"**Investimento:** {selected['buy_cost']:,.0f} ISK · "
                        f"**Lucro/unid.:** {selected.get('profit_per_unit', 0):,.2f} ISK"
                    )
                with right:
                    st.markdown(
                        f"**Rota:** {selected['jumps']} jumps · {selected['route_class']}"
                    )
                    st.markdown(
                        f"**Execução:** {selected.get('execution_class', 'Executável')} · "
                        f"**Liquidez:** {selected.get('liquidity_class', 'Baixa')}"
                    )
                    st.markdown(
                        f"**Book:** {selected.get('book_capacity', 0):,} unidades · "
                        f"cobertura {selected.get('book_coverage', 0):.1%}"
                    )
                    st.markdown(
                        f"**Snapshot:** {selected.get('market_age_minutes', 0):.1f} min"
                    )

            st.markdown('<div class="eve-section">Opportunity intelligence</div>', unsafe_allow_html=True)
            intelligence_left, intelligence_right = st.columns(2)

            with intelligence_left:
                st.markdown("**EXECUTION ECONOMICS**")
                cost_rows = [
                    {"Component": "Buy cost", "ISK": selected["buy_cost"]},
                    {"Component": "Sales tax", "ISK": selected.get("sales_tax", 0.0)},
                    {"Component": "Broker fee", "ISK": selected.get("broker_fee", 0.0)},
                    {"Component": "Transport", "ISK": selected.get("transport_cost", 0.0)},
                    {"Component": "Safety margin", "ISK": selected.get("safety_margin", 0.0)},
                    {"Component": "Total modeled costs", "ISK": selected.get("total_costs", 0.0)},
                    {"Component": "Sell revenue", "ISK": selected["sell_revenue"]},
                    {"Component": "Net profit", "ISK": selected["net_profit"]},
                ]
                st.dataframe(
                    cost_rows,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "ISK": st.column_config.NumberColumn(format="%,.0f ISK"),
                    },
                )

                e1, e2, e3 = st.columns(3)
                e1.metric("Margin", f'{selected.get("spread_pct", 0.0):.2%}')
                e2.metric("Profit / unit", f'{selected.get("profit_per_unit", 0.0):,.2f} ISK')
                e3.metric("Capital efficiency", f'{selected.get("capital_efficiency", 0.0):.2%}')

            with intelligence_right:
                st.markdown("**DECISION FACTORS**")
                factor_rows = [
                    {"Factor": "Execution", "Value": selected.get("execution_class", "Executável")},
                    {"Factor": "Liquidity", "Value": selected.get("liquidity_class", "Baixa")},
                    {"Factor": "Book depth", "Value": f'{selected.get("book_capacity", 0):,} units'},
                    {"Factor": "Book coverage", "Value": f'{selected.get("book_coverage", 0.0):.1%}'},
                    {"Factor": "Market age", "Value": f'{selected.get("market_age_minutes", 0.0):.1f} min'},
                    {"Factor": "Route", "Value": selected.get("route_class", "unknown")},
                    {"Factor": "Risk score", "Value": f'{selected.get("risk_score", 0.0):.1f}'},
                ]
                st.dataframe(factor_rows, width="stretch", hide_index=True)

                score_cols = st.columns(6)
                score_cols[0].metric("Execution", f'{selected.get("score_execution", 0.0):.0f}')
                score_cols[1].metric("Liquidity", f'{selected.get("score_liquidity", 0.0):.0f}')
                score_cols[2].metric("ROI", f'{selected.get("score_roi", 0.0):.0f}')
                score_cols[3].metric("ISK/h", f'{selected.get("score_isk_hour", 0.0):.0f}')
                score_cols[4].metric("Depth", f'{selected.get("score_depth", 0.0):.0f}')
                score_cols[5].metric("Route", f'{selected.get("score_route", 0.0):.0f}')
                st.caption(
                    f'Operational score: {selected.get("operational_score", 0.0):.1f}/100 · '
                    "composição transparente dos fatores acima"
                )

            st.markdown('<div class="eve-section">Route intelligence</div>', unsafe_allow_html=True)
            route_system_ids = selected.get("route_system_ids", [])
            route_rows = []
            if route_system_ids:
                with SessionLocal() as route_session:
                    route_systems = {
                        system.system_id: system
                        for system in route_session.query(SolarSystem)
                        .filter(SolarSystem.system_id.in_(route_system_ids))
                        .all()
                    }
                for position, system_id in enumerate(route_system_ids, start=1):
                    system = route_systems.get(system_id)
                    route_rows.append(
                        {
                            "Hop": position,
                            "System": system.name if system else f"system:{system_id}",
                            "Security": system.security_status if system else None,
                            "Class": system.security_class if system else "unknown",
                        }
                    )

            route_left, route_right = st.columns([2, 1])
            with route_left:
                if route_rows:
                    st.dataframe(
                        route_rows,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Security": st.column_config.NumberColumn(format="%.2f"),
                        },
                    )
                else:
                    st.info("Rota não disponível no SDE.")
            with route_right:
                r1, r2 = st.columns(2)
                r1.metric("Jumps", selected.get("jumps", 0))
                r2.metric("Min security", f'{selected.get("min_security_status", 0.0):.2f}')
                st.metric("Estimated time", f'{selected.get("estimated_minutes", 0.0):.0f} min')
                st.metric("High-sec", selected.get("highsec_systems", 0))
                st.metric("Low-sec", selected.get("lowsec_systems", 0))
                st.metric("Null-sec", selected.get("nullsec_systems", 0))

            st.markdown('<div class="eve-section">Order book / execution</div>', unsafe_allow_html=True)
            st.caption(
                "Profundidade executável do snapshot atual. A simulação consome as ordens "
                "na sequência necessária para executar a quantidade calculada."
            )

            buy_levels = selected.get("buy_levels", [])
            sell_levels = selected.get("sell_levels", [])
            e1, e2, e3, e4 = st.columns(4)
            e1.metric("Buy levels", selected.get("buy_levels_used", 0))
            e2.metric("Sell levels", selected.get("sell_levels_used", 0))
            e3.metric(
                "Marginal buy",
                f'{selected.get("buy_marginal_price", 0):,.2f} ISK',
            )
            e4.metric(
                "Marginal sell",
                f'{selected.get("sell_marginal_price", 0):,.2f} ISK',
            )

            depth_rows = []
            cumulative_buy = 0
            for level in sorted(buy_levels, key=lambda item: item["price"], reverse=True):
                cumulative_buy += level["quantity"]
                depth_rows.append(
                    {
                        "Price": level["price"],
                        "Buy depth": cumulative_buy,
                        "Sell depth": None,
                    }
                )
            cumulative_sell = 0
            for level in sorted(sell_levels, key=lambda item: item["price"]):
                cumulative_sell += level["quantity"]
                depth_rows.append(
                    {
                        "Price": level["price"],
                        "Buy depth": None,
                        "Sell depth": cumulative_sell,
                    }
                )
            depth_rows.sort(key=lambda row: row["Price"])

            if depth_rows:
                import plotly.graph_objects as go

                depth_figure = go.Figure()
                buy_depth = [row for row in depth_rows if row["Buy depth"] is not None]
                sell_depth = [row for row in depth_rows if row["Sell depth"] is not None]
                if buy_depth:
                    depth_figure.add_trace(
                        go.Scatter(
                            x=[row["Price"] for row in buy_depth],
                            y=[row["Buy depth"] for row in buy_depth],
                            mode="lines+markers",
                            name="Buy depth",
                            line_shape="hv",
                        )
                    )
                if sell_depth:
                    depth_figure.add_trace(
                        go.Scatter(
                            x=[row["Price"] for row in sell_depth],
                            y=[row["Sell depth"] for row in sell_depth],
                            mode="lines+markers",
                            name="Sell depth",
                            line_shape="hv",
                        )
                    )
                depth_figure.update_layout(
                    height=300,
                    margin={"l": 10, "r": 10, "t": 10, "b": 10},
                    xaxis_title="ISK / unit",
                    yaxis_title="Cumulative units",
                    hovermode="x unified",
                    legend={"orientation": "h", "y": 1.08},
                )
                st.plotly_chart(depth_figure, use_container_width=True)

            buy_rows = [
                {
                    "Order ID": level["order_id"],
                    "Price": level["price"],
                    "Quantity": level["quantity"],
                    "Total": level["value"],
                }
                for level in buy_levels
            ]
            sell_rows = [
                {
                    "Order ID": level["order_id"],
                    "Price": level["price"],
                    "Quantity": level["quantity"],
                    "Total": level["value"],
                }
                for level in sell_levels
            ]

            buy_col, sell_col = st.columns(2)
            with buy_col:
                st.markdown("**BUY ORDERS · consumed**")
                st.dataframe(
                    buy_rows,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Price": st.column_config.NumberColumn(format="%.2f ISK"),
                        "Quantity": st.column_config.NumberColumn(format="%d"),
                        "Total": st.column_config.NumberColumn(format="%,.0f ISK"),
                    },
                )
            with sell_col:
                st.markdown("**SELL ORDERS · consumed**")
                st.dataframe(
                    sell_rows,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Price": st.column_config.NumberColumn(format="%.2f ISK"),
                        "Quantity": st.column_config.NumberColumn(format="%d"),
                        "Total": st.column_config.NumberColumn(format="%,.0f ISK"),
                    },
                )

            st.caption(
                f'Execution: {selected["quantity"]:,} units · '
                f'buy avg {selected["avg_buy_price"]:,.2f} ISK · '
                f'sell avg {selected["avg_sell_price"]:,.2f} ISK · '
                f'net profit {selected["net_profit"]:,.0f} ISK'
            )

            st.subheader("Market watchlist")

            rank_options = {
                "Lucro líquido": "net_profit",
                "ISK/h": "isk_per_hour",
                "Menor capital": "capital_required",
                "Lucro por unidade": "profit_per_unit",
                "Score operacional": "operational_score",
            }
            rank_by = st.selectbox("Priorizar por", list(rank_options), index=4)
            rank_key = rank_options[rank_by]
            ranked = sorted(
                filtered,
                key=lambda item: item.get(rank_key, 0.0),
                reverse=rank_key != "capital_required",
            )

            for idx, item in enumerate(ranked[:6], start=1):
                execution = item.get("execution_class", "Executável")
                badge = {
                    "Escalável": "🟢",
                    "Executável": "🟡",
                    "Especulativa": "🔴",
                }.get(execution, "⚪")
                card = st.container(border=True)
                with card:
                    top = st.columns([3, 1, 1, 1])
                    top[0].markdown(f"### {idx}. {item['name']}")
                    top[0].caption(
                        f"{item['source_system_name']} → {item['destination_system_name']} · "
                        f"{item['quantity']:,} un. · {item['jumps']} jumps"
                    )
                    top[1].metric("Lucro", f"{item['net_profit']:,.0f}")
                    top[2].metric("ISK/h", f"{item['isk_per_hour']:,.0f}")
                    top[3].metric("Score", f"{item.get('operational_score', 0):.0f}/100")
                    st.caption(
                        f"{badge} {execution} · "
                        f"Capital {item['capital_required']:,.0f} ISK · "
                        f"{item.get('profit_per_unit', 0):,.2f} ISK/unid. · "
                        f"Book {item.get('book_capacity', 0):,} un."
                    )

            st.divider()
            st.subheader("Order-flow table")
            st.dataframe(
                rows,
                width="stretch",
                hide_index=True,
                column_config={
                    "Qtd": st.column_config.NumberColumn(format="%d"),
                    "Lucro/unid.": st.column_config.NumberColumn(format="%.2f ISK"),
                    "Capital necessário": st.column_config.NumberColumn(format="%.0f ISK"),
                    "Compra média": st.column_config.NumberColumn(format="%.2f ISK"),
                    "Venda média": st.column_config.NumberColumn(format="%.2f ISK"),
                    "Investido": st.column_config.NumberColumn(format="%,.0f ISK"),
                    "Lucro líquido": st.column_config.NumberColumn(format="%,.0f ISK"),
                    "ROI": st.column_config.NumberColumn(format="%.2%%"),
                    "ISK/h": st.column_config.NumberColumn(format="%.0f ISK/h"),
                    "Ef. capital": st.column_config.NumberColumn(format="%.2%%"),
                    "Spread": st.column_config.NumberColumn(format="%.2%%"),
                    "Cobertura book": st.column_config.NumberColumn(format="%.2%%"),
                    "Segurança mín.": st.column_config.NumberColumn(format="%.2f"),
                    "m³": st.column_config.NumberColumn(format="%.1f"),
                    "Idade book (min)": st.column_config.NumberColumn(format="%.1f"),
                },
            )
