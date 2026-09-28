from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime import SRC_DIR, load_repo_module

load_repo_module("arbitrageve.db.database", "arbitrageve/db/database.py")
load_repo_module("arbitrageve.db.models", "arbitrageve/db/models.py")
load_repo_module("arbitrageve.sde.loader", "arbitrageve/sde/loader.py")

import streamlit as st

from arbitrageve.config.regions import DOMAIN, REGIONS, THE_FORGE
from arbitrageve.config.settings import settings
from arbitrageve.db.models import Stargate
from arbitrageve.db.database import SessionLocal, init_db
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
                    {"Etapa": "Rotas vazias", "Quantidade": diagnostics.get("route_empty", 0)},
                    {"Etapa": "Rotas com formato inválido", "Quantidade": diagnostics.get("route_shape_invalid", 0)},
                    {"Etapa": "Sistemas de rota encontrados", "Quantidade": diagnostics.get("route_systems_found", 0)},
                    {"Etapa": "Sistemas de rota ausentes no SDE", "Quantidade": diagnostics.get("route_systems_missing", 0)},
                ],
                width="stretch",
                hide_index=True,
            )
    else:
        st.metric("Oportunidades", len(opportunities))
        st.dataframe(
            [
                {
                    "Item": item["name"],
                    "Rota": item["route_class"],
                    "Origem": f'{item["source_system_name"]} (loc {item["source_location_id"]})',
                    "Destino": f'{item["destination_system_name"]} (loc {item["destination_location_id"]})',
                    "Qtd": item["quantity"],
                    "Compra média": f'{item["avg_buy_price"]:,.2f}',
                    "Venda média": f'{item["avg_sell_price"]:,.2f}',
                    "Investido": f'{item["buy_cost"]:,.0f}',
                    "Lucro líquido": f'{item["net_profit"]:,.0f}',
                    "ROI": f'{item["roi"]:.2%}',
                    "ISK/h": f'{item["isk_per_hour"]:,.0f}',
                    "Ef. capital": f'{item["capital_efficiency"]:.2%}',
                    "Spread": f'{item["spread_pct"]:.2%}',
                    "Liquidez": item["liquidity_class"],
                    "Cobertura book": f'{item["book_coverage"]:.2%}',
                    "Book mínimo": item["book_capacity"],
                    "Book origem": item["source_book_volume"],
                    "Book destino": item["destination_book_volume"],
                    "Jumps": item["jumps"],
                    "Segurança mín.": f'{item["min_security_status"]:.2f}',
                    "Low-sec": item["lowsec_systems"],
                    "Null-sec": item["nullsec_systems"],
                    "m³": f'{item["volume_m3"]:,.1f}',
                }
                for item in opportunities
            ],
            width="stretch",
            hide_index=True,
        )
