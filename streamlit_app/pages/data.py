from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime import load_repo_module

load_repo_module("arbitrageve.db.database", "arbitrageve/db/database.py")
load_repo_module("arbitrageve.db.models", "arbitrageve/db/models.py")
load_repo_module("arbitrageve.sde.loader", "arbitrageve/sde/loader.py")

import streamlit as st
from sqlalchemy import func, select

from arbitrageve.db.database import DATABASE_URL, SessionLocal, init_db
from arbitrageve.db.models import Item, MarketOrder, Region, SolarSystem, Stargate
from arbitrageve.esi.client import ESIRequestError
from arbitrageve.market.collector import collect_region
from arbitrageve.sde.loader import (
    LOADER_VERSION,
    download_latest_sde,
    inspect_types_archive,
    load_regions_from_archive,
    load_solar_systems_from_archive,
    load_stargates_from_archive,
    load_types,
)
from theme import apply_eve_theme, render_topbar

init_db()
apply_eve_theme()
render_topbar("DATA CENTER")

st.caption("Static universe data · market snapshots · database health")

with SessionLocal() as session:
    item_count = session.scalar(select(func.count()).select_from(Item)) or 0
    region_count = session.scalar(select(func.count()).select_from(Region)) or 0
    system_count = session.scalar(select(func.count()).select_from(SolarSystem)) or 0
    stargate_count = session.scalar(select(func.count()).select_from(Stargate)) or 0
    order_count = session.scalar(select(func.count()).select_from(MarketOrder)) or 0
    snapshot_count = session.scalar(
        select(func.count(func.distinct(MarketOrder.region_id))).select_from(MarketOrder)
    ) or 0
    latest_snapshot = session.scalar(select(func.max(MarketOrder.collected_at)).select_from(MarketOrder))

st.markdown('<div class="eve-section">Database status</div>', unsafe_allow_html=True)
status_cols = st.columns(5)
status_cols[0].metric("Items", f"{item_count:,}")
status_cols[1].metric("Regions", f"{region_count:,}")
status_cols[2].metric("Systems", f"{system_count:,}")
status_cols[3].metric("Stargates", f"{stargate_count:,}")
status_cols[4].metric("Orders", f"{order_count:,}")

db_state = "ONLINE" if DATABASE_URL else "UNKNOWN"
sde_state = "READY" if item_count and region_count and system_count and stargate_count else "INCOMPLETE"
market_state = "READY" if order_count else "EMPTY"

state_cols = st.columns(3)
state_cols[0].markdown(
    f'<span class="eve-pill">DATABASE · {db_state}</span>',
    unsafe_allow_html=True,
)
state_cols[1].markdown(
    f'<span class="eve-pill">SDE · {sde_state}</span>',
    unsafe_allow_html=True,
)
state_cols[2].markdown(
    f'<span class="eve-pill">MARKET · {market_state}</span>',
    unsafe_allow_html=True,
)

st.divider()

sde_col, market_col = st.columns([1, 1])

with sde_col:
    st.markdown('<div class="eve-section">Static universe / SDE</div>', unsafe_allow_html=True)
    st.write(
        "O SDE oficial alimenta tipos de itens, regiões, sistemas solares e "
        "stargates usados pelo scanner, pela análise de segurança e pelo roteamento local."
    )
    st.caption(f"Loader: {LOADER_VERSION}")

    if st.button("Atualizar SDE", type="primary", use_container_width=True):
        progress = st.progress(0, text="Baixando SDE oficial...")
        try:
            archive = Path("/tmp/arbitrageve/eve-sde-latest.zip")
            download_latest_sde(archive)

            progress.progress(25, text="Validando estrutura do SDE...")
            diagnostics = inspect_types_archive(archive)
            if diagnostics["sample_named"] == 0:
                st.error("Nenhum nome foi encontrado nos primeiros registros de types.jsonl.")
                progress.empty()
                st.stop()

            progress.progress(45, text="Importando tipos e regiões...")
            with SessionLocal() as session:
                item_loaded = load_types(archive, session)
                region_loaded = load_regions_from_archive(archive, session)

                progress.progress(70, text="Importando sistemas e stargates...")
                system_loaded = load_solar_systems_from_archive(archive, session)
                stargate_loaded = load_stargates_from_archive(archive, session)

            progress.progress(100, text="SDE carregado.")
            st.success(
                f"SDE atualizado: {item_loaded:,} itens · {region_loaded:,} regiões · "
                f"{system_loaded:,} sistemas · {stargate_loaded:,} stargates."
            )
            st.rerun()
        except (OSError, ValueError, RuntimeError) as exc:
            progress.empty()
            st.error(f"Falha ao atualizar o SDE: {exc}")

with market_col:
    st.markdown('<div class="eve-section">Market snapshots</div>', unsafe_allow_html=True)
    st.write(
        "A coleta usa a paginação X-Pages da ESI e só substitui uma região "
        "depois que todas as páginas foram baixadas."
    )
    if latest_snapshot:
        st.caption(
            f"Último snapshot: {latest_snapshot.strftime('%Y-%m-%d %H:%M:%S')} · "
            f"{snapshot_count:,} regiões com dados"
        )
    else:
        st.caption("Nenhum snapshot de mercado encontrado.")

    with SessionLocal() as session:
        db_regions = session.scalars(select(Region).order_by(Region.name)).all()

    if not db_regions:
        st.warning("Nenhuma região do SDE está carregada. Atualize o SDE antes de coletar o mercado.")
        selected_regions = []
    else:
        region_ids = [region.region_id for region in db_regions]
        selected_regions = st.multiselect(
            "Regiões",
            options=region_ids,
            default=region_ids[:2],
            format_func=lambda region_id: next(
                region.name for region in db_regions if region.region_id == region_id
            ),
        )

    if st.button("Atualizar mercado", use_container_width=True):
        if not selected_regions:
            st.warning("Selecione pelo menos uma região.")
        else:
            for region_id in selected_regions:
                region_name = next(
                    region.name for region in db_regions if region.region_id == region_id
                )
                progress = st.progress(0, text=f"Preparando {region_name}...")
                status = st.empty()

                def update_progress(
                    page,
                    pages,
                    orders,
                    region_name=region_name,
                    progress_bar=progress,
                ):
                    ratio = page / pages if pages else 1.0
                    progress_bar.progress(
                        min(1.0, ratio),
                        text=f"{region_name}: página {page}/{pages} — {orders:,} ordens",
                    )

                try:
                    with SessionLocal() as session:
                        count = collect_region(
                            session,
                            region_id,
                            progress_callback=update_progress,
                        )
                    progress.progress(1.0, text=f"{region_name} concluído.")
                    status.success(f"{region_name}: {count:,} ordens armazenadas.")
                except (ESIRequestError, OSError, ValueError, RuntimeError) as exc:
                    progress.empty()
                    status.error(f"{region_name}: falha na coleta: {exc}")

st.divider()

st.markdown('<div class="eve-section">Market snapshot registry</div>', unsafe_allow_html=True)

with SessionLocal() as session:
    snapshot_rows = session.execute(
        select(
            Region.name,
            func.count(MarketOrder.order_id),
            func.max(MarketOrder.collected_at),
        )
        .join(MarketOrder, MarketOrder.region_id == Region.region_id)
        .group_by(Region.region_id, Region.name)
        .order_by(Region.name)
    ).all()

if snapshot_rows:
    table_rows = []
    now = datetime.now(UTC).replace(tzinfo=None)
    for name, orders, collected_at in snapshot_rows:
        age_minutes = max(0.0, (now - collected_at).total_seconds() / 60) if collected_at else None
        if age_minutes is None:
            state = "UNKNOWN"
        elif age_minutes <= 60:
            state = "FRESH"
        elif age_minutes <= 360:
            state = "STALE"
        else:
            state = "EXPIRED"
        table_rows.append(
            {
                "Region": name,
                "Orders": orders,
                "Last snapshot": collected_at.strftime("%Y-%m-%d %H:%M:%S") if collected_at else "—",
                "Age (min)": round(age_minutes, 1) if age_minutes is not None else None,
                "State": state,
            }
        )
    st.dataframe(table_rows, use_container_width=True, hide_index=True)
else:
    st.info("Nenhum snapshot de mercado disponível. Use Market snapshots para coletar uma região.")

st.divider()

st.markdown('<div class="eve-section">System diagnostics</div>', unsafe_allow_html=True)
diagnostic_cols = st.columns(4)
diagnostic_cols[0].metric("Database", db_state)
diagnostic_cols[1].metric("SDE", sde_state)
diagnostic_cols[2].metric("Market regions", f"{snapshot_count:,}")
diagnostic_cols[3].metric("Latest snapshot", latest_snapshot.strftime("%H:%M:%S") if latest_snapshot else "—")

if not item_count or not region_count or not system_count or not stargate_count:
    st.warning(
        "O universo está incompleto. Atualize o SDE antes de executar o scanner global."
    )
elif not order_count:
    st.warning(
        "O universo está carregado, mas ainda não existem snapshots de mercado. "
        "Colete pelo menos uma região para habilitar oportunidades."
    )
