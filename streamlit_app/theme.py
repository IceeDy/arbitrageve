from __future__ import annotations

import streamlit as st


def apply_eve_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --eve-bg: #080d10;
            --eve-panel: #10191d;
            --eve-panel-2: #152126;
            --eve-border: #26383e;
            --eve-muted: #82949a;
            --eve-accent: #4fb3a2;
            --eve-accent-2: #7ed8c8;
        }

        .stApp {
            background: radial-gradient(circle at 75% -10%, #15262b 0, var(--eve-bg) 42%);
        }

        [data-testid="stHeader"] {
            background: rgba(8, 13, 16, .92);
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0d171b 0%, #091013 100%);
            border-right: 1px solid var(--eve-border);
        }

        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: var(--eve-accent-2);
            letter-spacing: .03em;
            text-transform: uppercase;
            font-size: .78rem;
        }

        .eve-topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            padding: .35rem 0 .8rem;
            border-bottom: 1px solid var(--eve-border);
            margin-bottom: 1rem;
        }

        .eve-brand {
            font-size: 1.35rem;
            font-weight: 700;
            letter-spacing: .04em;
            color: #e6eeee;
        }

        .eve-brand span {
            color: var(--eve-accent-2);
        }

        .eve-status {
            color: var(--eve-muted);
            font-size: .75rem;
            letter-spacing: .04em;
        }

        div[data-testid="stMetric"] {
            background: linear-gradient(180deg, var(--eve-panel-2), var(--eve-panel));
            border: 1px solid var(--eve-border);
            border-radius: 4px;
            padding: .65rem .75rem;
        }

        div[data-testid="stMetricLabel"] {
            color: var(--eve-muted);
            font-size: .7rem;
            text-transform: uppercase;
            letter-spacing: .05em;
        }

        div[data-testid="stMetricValue"] {
            color: #e3ecec;
            font-size: 1.15rem;
        }

        div[data-testid="stDataFrame"] {
            border: 1px solid var(--eve-border);
            border-radius: 4px;
            overflow: hidden;
        }

        [data-testid="stExpander"] {
            background: var(--eve-panel);
            border: 1px solid var(--eve-border);
            border-radius: 4px;
        }

        .block-container {
            padding-top: 1.2rem;
            padding-bottom: 2rem;
            max-width: 1700px;
        }

        .eve-section {
            color: var(--eve-muted);
            text-transform: uppercase;
            letter-spacing: .09em;
            font-size: .7rem;
            margin: .25rem 0 .55rem;
        }

        .eve-pill {
            display: inline-block;
            border: 1px solid var(--eve-border);
            background: #0c1518;
            color: var(--eve-muted);
            border-radius: 3px;
            padding: .16rem .42rem;
            margin-right: .25rem;
            font-size: .7rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_topbar(status: str = "MARKET SCANNER") -> None:
    st.markdown(
        f"""
        <div class="eve-topbar">
            <div class="eve-brand">Arbitrag<span>EVE</span></div>
            <div class="eve-status">{status} · EXECUTION INTELLIGENCE</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
