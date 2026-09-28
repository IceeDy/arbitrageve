import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime import load_repo_module

load_repo_module("arbitrageve.db.database", "arbitrageve/db/database.py")
load_repo_module("arbitrageve.db.models", "arbitrageve/db/models.py")
load_repo_module("arbitrageve.sde.loader", "arbitrageve/sde/loader.py")

import streamlit as st

from arbitrageve.config.regions import REGIONS, THE_FORGE
from arbitrageve.config.settings import settings
from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.db.models import Stargate
from arbitrageve.market.costs import TradeCosts
from arbitrageve.market.metrics import ExecutionProfile
from arbitrageve.sde.routes import LocalRouteClient
from arbitrageve.services.opportunities import find_opportunities
from arbitrageve.services.risk import RiskProfile

st.set_page_config(page_title="ArbitrageVE", page_icon="📈", layout="wide")
init_db()

st.title("ArbitrageVE")
st.caption("EVE Online cross-region market arbitrage scanner • roteamento local via SDE")
# Scanner diagnostics API: 2026-09-28

with st.sidebar:
    st.header("Scanner")
    capital = st.number_input("Capital (ISK)", min_value=0.0, value=settings.capital_isk, step=1_000_000.0)
    cargo = st.number_input("Cargo (m³)", min_value=0.0, value=settings.cargo_m3, step=10.0)
    source = st.selectbox("Comprar em", options=list(REGIONS), format_func=lambda x: REGIONS[x])
    destination = st.selectbox(
        "Vender em",
        options=list(REGIONS),
        index=1 if source == THE_FORGE else 0,
        format_func=lambda x: REGIONS[x],
    )
    min_roi = st.slider("ROI líquido mínimo", 0.0, 1.0, 0.05, 0.01)
    min_profit = st.number_input("Lucro líquido mínimo (ISK)", min_value=0.0, value=100_000.0, step=100_000.0)
    max_market_age = st.number_input("Idade máxima do snapshot (min)", min_value=0.0, value=60.0, step=5.0)

    st.divider()
    st.subheader("Rota")
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
    st.subheader("Execução")
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
    st.subheader("Custos")
    sales_tax = st.number_input("Sales tax (%)", min_value=0.0, max_value=100.0, value=7.5, step=0.1) / 100
    broker_fee = st.number_input("Broker fee (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.1) / 100
    transport_flat = st.number_input("Transporte por viagem (ISK)", min_value=0.0, value=0.0, step=10_000.0)
    transport_m3_jump = st.number_input("Transporte (ISK/m³/jump)", min_value=0.0, value=0.0, step=10.0)
    safety_margin = st.number_input("Margem de segurança sobre custos (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.5) / 100

if source == destination:
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

        opportunities = find_opportunities(
            session,
            source,
            destination,
            capital,
            cargo,
            min_roi,
            min_profit,
            costs=costs,
            route_client=LocalRouteClient(session),
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
        ]
        st.metric("Oportunidades", len(filtered), delta=f"{len(opportunities) - len(filtered)} ocultas pelo filtro" if len(filtered) != len(opportunities) else None)

        if not filtered:
            st.info("Nenhuma oportunidade corresponde ao filtro de execução selecionado.")
        else:
            total_required = sum(item["capital_required"] for item in filtered)
            scalable_count = sum(item.get("scalable", False) for item in filtered)
            speculative_count = sum(item.get("execution_class") == "Especulativa" for item in filtered)
            c1, c2, c3 = st.columns(3)
            c1.metric("Capital necessário", f"{total_required:,.0f} ISK")
            c2.metric("Escaláveis", scalable_count)
            c3.metric("Especulativas", speculative_count)

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
