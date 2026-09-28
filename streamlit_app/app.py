import streamlit as st

from arbitrageve.config.regions import DOMAIN, REGIONS, THE_FORGE
from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.services.opportunities import find_opportunities

st.set_page_config(page_title="ArbitrageVE", page_icon="📈", layout="wide")
init_db()

st.title("ArbitrageVE")
st.caption("EVE Online cross-region market arbitrage scanner")

with st.sidebar:
    st.header("Scanner")
    capital = st.number_input("Capital (ISK)", min_value=0.0, value=100_000_000.0, step=1_000_000.0)
    cargo = st.number_input("Cargo (m³)", min_value=0.0, value=400.0, step=10.0)
    source = st.selectbox("Comprar em", options=list(REGIONS), format_func=lambda x: REGIONS[x])
    destination = st.selectbox(
        "Vender em",
        options=list(REGIONS),
        index=1 if source == THE_FORGE else 0,
        format_func=lambda x: REGIONS[x],
    )
    min_roi = st.slider("ROI mínimo", 0.0, 1.0, 0.05, 0.01)
    min_profit = st.number_input("Lucro mínimo (ISK)", min_value=0.0, value=100_000.0, step=100_000.0)

if source == destination:
    st.warning("Escolha regiões diferentes.")
else:
    with SessionLocal() as session:
        opportunities = find_opportunities(
            session,
            source,
            destination,
            capital,
            cargo,
            min_roi,
            min_profit,
        )

    if not opportunities:
        st.info("Nenhuma oportunidade encontrada. Execute a coleta de mercado e cadastre o SDE dos itens.")
    else:
        st.metric("Oportunidades", len(opportunities))
        st.dataframe(
            [
                {
                    "Item": item["name"],
                    "Compra": f'{item["buy_price"]:,.2f}',
                    "Venda": f'{item["sell_price"]:,.2f}',
                    "Qtd": item["quantity"],
                    "Lucro ISK": f'{item["net_profit"]:,.0f}',
                    "ROI": f'{item["roi"]:.2%}',
                    "m³": f'{item["volume_m3"]:,.1f}',
                }
                for item in opportunities
            ],
            use_container_width=True,
            hide_index=True,
        )
