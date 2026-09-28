# ArbitrageVE

EVE Online market arbitrage scanner.

## Architecture

- ESI client and market collector
- SQLite + SQLAlchemy persistence
- SDE integration point
- Cross-region arbitrage engine
- Streamlit dashboard

Initial target markets: Amarr (Domain) and Jita (The Forge).

## Run

```bash
pip install -e .
streamlit run streamlit_app/app.py
```
