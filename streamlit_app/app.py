import streamlit as st

from arbitrageve.config.regions import DOMAIN, REGIONS, THE_FORGE
from arbitrageve.config.settings import settings
from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.esi.routes import RouteClient
from arbitrageve.market.costs import TradeCosts
from arbitrageve.services.opportunities import find_opportunities

st.set_page_config(page_title="ArbitrageVE", page_icon="📈", layout="wide")
init_db()

st.title("ArbitrageVE")
st.caption("EVE Online cross-region market arbitrage scanner")

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
    route_preference = st.selectbox("Preferência", ["Shorter", "Safer", "LessSecure"], format_func=lambda value: {"Shorter": "Mais curta", "Safer": "Mais segura", "LessSecure": "Menos segura"}[value])
    security_penalty = st.slider("Penalidade de segurança", 0, 100, 50, 5)

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

    with SessionLocal() as session:
        opportunities = find_opportunities(
            session,
            source,
            destination,
            capital,
            cargo,
            min_roi,
            min_profit,
            costs=costs,
            route_client=RouteClient(),
            route_preference=route_preference,
            security_penalty=security_penalty,
        )

    if not opportunities:
        st.info("Nenhuma oportunidade encontrada. Execute a coleta de mercado e cadastre o SDE dos itens.")
    else:
        st.metric("Oportunidades", len(opportunities))
        st.dataframe(
            [
                {
                    "Item": item["name"],
                    "Qtd": item["quantity"],
                    "Compra média": f'{item["avg_buy_price"]:,.2f}',
                    "Venda média": f'{item["avg_sell_price"]:,.2f}',
                    "Investido": f'{item["buy_cost"]:,.0f}',
                    "Receita": f'{item["sell_revenue"]:,.0f}',
                    "Taxas": f'{item["total_costs"]:,.0f}',
                    "Transporte": f'{item["transport_cost"]:,.0f}',
                    "Lucro líquido": f'{item["net_profit"]:,.0f}',
                    "ROI líquido": f'{item["roi"]:.2%}',
                    "Jumps": item["jumps"],
                    "m³": f'{item["volume_m3"]:,.1f}',
                }
                for item in opportunities
            ],
            use_container_width=True,
            hide_index=True,
        )
