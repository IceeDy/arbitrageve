# ArbitrageVE

EVE Online market arbitrage scanner focused on executable cross-region opportunities.

## Current architecture

- **ESI client** with retries and market pagination
- **SQLite + SQLAlchemy** persistence
- **Market order schema** with price, volume, location, side and collection timestamp
- **Cross-region arbitrage engine** constrained by capital and cargo
- **Streamlit dashboard** for scanning opportunities
- **SDE integration point** for item names and volumes

Initial target markets:

- Jita — The Forge
- Amarr — Domain

## Setup

Python 3.13+:

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

Create `.env` from `.env.example`, then:

```bash
streamlit run streamlit_app/app.py
```

Collect the initial market snapshot:

```bash
python scripts/collect_market.py
```

Run tests:

```bash
pytest
```

## Next milestone

Implement the SDE loader and a proper market snapshot/history strategy. Then add route cost, taxes/fees, order depth and a ranking model based on the actual ISK available for the Alpha/Omega progression.
