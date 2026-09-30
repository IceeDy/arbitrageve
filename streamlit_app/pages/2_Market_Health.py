import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime import load_repo_module

load_repo_module("arbitrageve.db.database", "arbitrageve/db/database.py")
load_repo_module("arbitrageve.db.models", "arbitrageve/db/models.py")

from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.services.market_worker import audit_region_refresh

st.set_page_config(
    page_title="ArbitragEVE · Market Health",
    page_icon="🛰️",
    layout="wide",
)

init_db()

st.title("Market Refresh Health")
st.caption(
    "Visão operacional da coleta regional. O intervalo alvo é calculado "
    "automaticamente pelo volume de ordens de cada região."
)

with SessionLocal() as session:
    audit = audit_region_refresh(session)

if not audit:
    st.warning("Nenhuma região encontrada no PostgreSQL.")
    st.stop()

due_count = sum(row["status"] == "DUE" for row in audit)
fresh_count = sum(row["status"] == "FRESH" for row in audit)
never_count = sum(row["status"] == "NEVER" for row in audit)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Regiões", len(audit))
c2.metric("Fresh", fresh_count)
c3.metric("Due", due_count)
c4.metric("Sem coleta", never_count)

rows = []
for row in audit:
    rows.append(
        {
            "Região": row["region"],
            "Status": row["status"],
            "Ordens": row["order_count"],
            "Última coleta": row["last_collected"] or "Nunca",
            "Idade (min)": row["age_minutes"],
            "Intervalo alvo (min)": row["target_refresh_minutes"],
            "Razão atraso": row["overdue_ratio"],
            "Prioridade": (
                row["priority"] if row["priority"] < 10_000 else "Normal"
            ),
        }
    )

st.dataframe(
    rows,
    width="stretch",
    hide_index=True,
    column_config={
        "Ordens": st.column_config.NumberColumn(format="%,d"),
        "Idade (min)": st.column_config.NumberColumn(format="%.1f"),
        "Intervalo alvo (min)": st.column_config.NumberColumn(format="%.1f"),
        "Razão atraso": st.column_config.NumberColumn(format="%.2fx"),
    },
)

st.divider()
st.subheader("Como interpretar")
st.markdown(
    """
- **FRESH**: o snapshot ainda está dentro do intervalo adaptativo calculado.
- **DUE**: o snapshot ultrapassou o intervalo alvo e a região está elegível para o próximo worker.
- **NEVER**: a região existe no universo, mas ainda não possui snapshot de mercado.
- **Intervalo alvo**: diminui conforme aumenta o volume de ordens, respeitando os limites configurados.
- **Razão atraso**: idade do snapshot dividida pelo intervalo alvo. Valores acima de 1.0x estão atrasados.
"""
)
