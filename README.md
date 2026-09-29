# ArbitrageVE

EVE Online market arbitrage scanner focused on executable cross-region opportunities.

## Current architecture

- **ESI client** with retries, pagination and the current POST route API
- **SQLite for local development + PostgreSQL for persistent hosting** via SQLAlchemy
- **Persistent app state** for SDE and worker lifecycle metadata
- **Market order schema** with price, volume, location, side and collection timestamp
- **Cross-region arbitrage engine** constrained by capital, cargo and order-book depth
- **Net profitability model** with sales tax, optional broker fee, transport and safety margin
- **Route-aware scanning** using the systems attached to the selected market locations
- **Route risk engine** with high-sec, low-sec, null-sec filters and maximum jumps
- **Execution model** with configurable operation time, minutes per jump and optional return trip
- **ISK/hour and capital-efficiency metrics** for ranking opportunities
- **Streamlit dashboard** for scanning and configuration
- **Official EVE SDE loader** for item names, volumes, system names, security status and static stargate connections
- **Incremental market worker** that refreshes stale regions instead of blocking the application on a full-universe collection

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

Bootstrap the official SDE:

```bash
python scripts/bootstrap_data.py
```

Force an SDE refresh:

```bash
python scripts/bootstrap_data.py --force
```

Collect the next stale market region:

```bash
python scripts/market_worker.py
```

Run tests:

```bash
pytest
```

## Production persistence

For hosted deployment, set `DATABASE_URL` to a persistent PostgreSQL database. Do not rely on the local SQLite filesystem for production data.

The Streamlit application bootstraps the SDE only when the persistent database is missing universe data. The market worker also performs this bootstrap, so the first scheduled worker run can initialize an empty persistent database without requiring a browser session.

GitHub Actions provides two scheduled jobs:

- **Market Worker:** runs every 15 minutes and automatically schedules up to two due regions per run. Each region receives an adaptive refresh interval based on its latest order count: higher-volume regions are refreshed more frequently, while low-volume regions can wait longer.
- **SDE Refresh:** runs weekly and force-refreshes the official SDE.

Both workflows require the repository secrets `DATABASE_URL` and `ESI_USER_AGENT`.

The market worker records its last start, completion, status, regions and error in `app_state`. The Data Center page exposes this state so deployment problems are visible without inspecting workflow logs.

## Scanner model

The scanner buys from existing sell orders and sells into existing buy orders. It consumes multiple order-book levels and limits quantity by available source inventory, destination demand, capital and cargo capacity.

The result includes gross profit, modeled costs, net profit, ROI, capital efficiency, transport cost, route length and estimated ISK/hour.

## Route and risk model

Routes are calculated locally from the official SDE stargate graph using the route preference (`Shorter`, `Safer` or `LessSecure`) and security penalty. This avoids making one ESI `/route` request per candidate pair; ESI remains available as an API client for other operations.

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

The worker calculates a target refresh interval from the latest snapshot order count, bounded by configurable minimum and maximum intervals. Selection is based on how overdue each region is, with configured hub priority used as a tie-breaker. This makes market freshness automatic instead of requiring manual regional updates while keeping ESI collection incremental.

## Next milestones

1. Add station/location metadata for human-readable market lanes.
2. Improve lane selection beyond one source station and one destination station.
3. Add character skills/standings profiles for more accurate fee assumptions.
4. Add execution tracking and realized ISK/hour.
5. Add historical opportunity snapshots and capital-turnover analysis.
