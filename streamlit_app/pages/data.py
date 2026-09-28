import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime import load_repo_module

load_repo_module("arbitrageve.db.database", "arbitrageve/db/database.py")
load_repo_module("arbitrageve.db.models", "arbitrageve/db/models.py")
load_repo_module("arbitrageve.sde.loader", "arbitrageve/sde/loader.py")

import streamlit as st

from arbitrageve.config.regions import DOMAIN, REGIONS, THE_FORGE
from arbitrageve.db.database import SessionLocal, init_db
from arbitrageve.esi.client import ESIRequestError
from arbitrageve.market.collector import collect_region
from arbitrageve.sde.loader import (
    LOADER_VERSION,
    download_latest_sde,
    inspect_types_archive,
    load_solar_systems_from_archive,
    load_stargates_from_archive,
    load_types,
)

init_db()

st.title("Dados")
st.caption("Atualização do SDE e snapshots de mercado")

st.subheader("Static Data Export (SDE)")
st.write(
    "O SDE fornece os tipos de itens e os sistemas solares usados pelo scanner "
    "para nomes, volumes, análise de segurança e roteamento local."
)
st.caption(f"Loader SDE: {LOADER_VERSION}")

if st.button("Atualizar SDE", type="primary"):
    progress = st.progress(0, text="Baixando SDE oficial...")
    try:
        from pathlib import Path

        archive = Path("/tmp/arbitrageve/eve-sde-latest.zip")
        download_latest_sde(archive)
        progress.progress(35, text="SDE baixado. Inspecionando types.jsonl...")

        diagnostics = inspect_types_archive(archive)
        st.info(
            f"types.jsonl: {diagnostics['member']} | "
            f"amostra: {diagnostics['sample_lines']} linhas | "
            f"_key: {diagnostics['sample_keyed']} | "
            f"com nome: {diagnostics['sample_named']}"
        )

        if diagnostics["sample_named"] == 0:
            st.error("Nenhum nome foi encontrado nos primeiros 100 registros de types.jsonl.")
            st.json(diagnostics["samples"])
            progress.empty()
            st.stop()

        progress.progress(60, text="Importando tipos, sistemas e stargates...")
        with SessionLocal() as session:
            item_count = load_types(archive, session)
            system_count = load_solar_systems_from_archive(archive, session)
            stargate_count = load_stargates_from_archive(archive, session)

        progress.progress(100, text="SDE carregado.")
        st.success(
            f"SDE carregado: {item_count:,} tipos, {system_count:,} sistemas "
            f"e {stargate_count:,} stargates."
        )
        if item_count == 0:
            st.error(
                "A inspeção encontrou nomes, mas a importação retornou 0. "
                "Isso indica erro de parsing/execução diferente do diagnóstico."
            )
    except (OSError, ValueError, RuntimeError) as exc:
        progress.empty()
        st.error(f"Falha ao atualizar o SDE: {exc}")

st.divider()

st.subheader("Market Data")
st.write(
    "A coleta usa a paginação X-Pages da ESI e substitui cada região por um "
    "snapshot completo somente depois que todas as páginas forem baixadas."
)

region_options = list(REGIONS)
selected_regions = st.multiselect(
    "Regiões",
    options=region_options,
    default=[THE_FORGE, DOMAIN],
    format_func=lambda region_id: REGIONS[region_id],
)

if st.button("Atualizar mercado"):
    if not selected_regions:
        st.warning("Selecione pelo menos uma região.")
    else:
        for region_id in selected_regions:
            progress = st.progress(0, text=f"Preparando {REGIONS[region_id]}...")
            status = st.empty()

            def update_progress(
                page,
                pages,
                orders,
                region_name=REGIONS[region_id],
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
                progress.progress(1.0, text=f"{REGIONS[region_id]} concluído.")
                status.success(f"{REGIONS[region_id]}: {count:,} ordens armazenadas.")
            except (ESIRequestError, OSError, ValueError, RuntimeError) as exc:
                progress.empty()
                status.error(f"{REGIONS[region_id]}: falha na coleta: {exc}")

st.divider()

st.subheader("Status do banco")

with SessionLocal() as session:
    from sqlalchemy import func, select

    from arbitrageve.db.models import Item, MarketOrder, SolarSystem, Stargate

    item_count = session.scalar(select(func.count()).select_from(Item)) or 0
    system_count = session.scalar(select(func.count()).select_from(SolarSystem)) or 0
    order_count = session.scalar(select(func.count()).select_from(MarketOrder)) or 0
    stargate_count = session.scalar(select(func.count()).select_from(Stargate)) or 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Tipos de item", f"{item_count:,}")
col2.metric("Sistemas", f"{system_count:,}")
col3.metric("Stargates", f"{stargate_count:,}")
col4.metric("Ordens", f"{order_count:,}")
