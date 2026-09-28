# ArbitrageVE

EVE Online market arbitrage scanner focused on executable cross-region opportunities.

## Current architecture

- **ESI client** with retries, pagination and the current POST route API
- **SQLite + SQLAlchemy** persistence
- **Market order schema** with price, volume, location, side and collection timestamp
- **Cross-region arbitrage engine** constrained by capital, cargo and order-book depth
- **Net profitability model** with sales tax, optional broker fee, transport and safety margin
- **Route-aware scanning** using the systems attached to the selected market locations
- **Route risk engine** with high-sec, low-sec, null-sec filters and maximum jumps
- **Execution model** with configurable operation time, minutes per jump and optional return trip
- **ISK/hour and capital-efficiency metrics** for ranking opportunities
- **Streamlit dashboard** for scanning and configuration
- **Official EVE SDE loader** for item names, volumes, system names and security status

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

Load item and solar-system metadata:

```bash
python scripts/load_sde.py
```

Run tests:

```bash
pytest
```

## Scanner model

The scanner buys from existing sell orders and sells into existing buy orders. It consumes multiple order-book levels and limits quantity by available source inventory, destination demand, capital and cargo capacity.

The result includes gross profit, modeled costs, net profit, ROI, capital efficiency, transport cost, route length and estimated ISK/hour.

## Route and risk model

Routes are calculated through ESI using the route preference (`Shorter`, `Safer` or `LessSecure`) and security penalty. The route result is then inspected against the local SDE metadata.

The dashboard can block low-sec and null-sec routes and impose a maximum jump count. Security classification follows EVE's documented thresholds: high-sec at security status >= 0.45, low-sec above 0 and below 0.45, and null-sec at or below 0.0.

If security metadata is missing and the user has enabled restrictive security filters, the scanner fails closed instead of pretending that the route is known.

## Execution model

Estimated operation time is configurable because actual hauling time depends on the ship, fittings, docking, undocking, loading, market interaction and pilot behavior.

The model supports:

- fixed minutes per operation;
- minutes per jump;
- optional return-trip time.

The resulting **ISK/hour is an estimate**, not a realized performance metric. Future versions should replace the estimate with execution history.

## Market refresh

Market collection fetches every page before replacing the previous region snapshot. This prevents stale orders from remaining in the database after they disappear from the latest complete ESI snapshot.

## Next milestones

1. Load station names and richer location metadata from SDE.
2. Improve lane selection beyond one source station and one destination station.
3. Add character skills/standings profiles for more accurate fee assumptions.
4. Add execution tracking and realized ISK/hour.
5. Add historical opportunity snapshots and capital-turnover analysis.
