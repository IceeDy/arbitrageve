# ArbitrageVE

EVE Online market arbitrage scanner focused on executable cross-region opportunities.

## Current architecture

- **ESI client** with retries and market pagination
- **SQLite + SQLAlchemy** persistence
- **Market order schema** with price, volume, location, side and collection timestamp
- **Cross-region arbitrage engine** constrained by capital and cargo
- **Order-book depth** using multiple price levels instead of top-of-book only
- **Net profitability model** with sales tax, optional broker fee, transport and safety margin
- **Route-aware scanning** using the systems attached to the selected market locations
- **Streamlit dashboard** for scanning and configuring trade costs
- **Official EVE SDE loader** for item names and volumes

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

## Cost model

The scanner currently models an immediate cross-region trade: it buys from existing sell orders and sells into existing buy orders. Sales tax is therefore the primary market fee. Broker fee is configurable for future strategies that create non-immediate sell orders.

CCP's current support documentation states that sales tax starts at 7.5% and can be reduced through Accounting, while broker fee starts at 3% for non-immediate orders and depends on Broker Relations and standings. These rates are configurable in the dashboard rather than hard-coded into the profitability engine.

Transport can be represented as a flat trip cost plus an ISK/m³/jump component. A safety margin can be applied to the modeled costs to avoid treating small theoretical spreads as guaranteed profit.

## Execution assumptions

- Source inventory is restricted to the location of the cheapest source order selected for the opportunity.
- Destination sales are restricted to the location of the highest destination buy order selected for the opportunity.
- Route jumps are obtained from ESI when a route is needed.
- Quantity is limited by capital, cargo capacity and available order-book volume.
- Results are ranked by **net profit**, after modeled costs.

## SDE and market refresh

Load the official EVE SDE into the local SQLite database:

```bash
python scripts/load_sde.py
```

The loader downloads the latest official JSONL SDE archive and imports type names and volumes. The SDE is published by CCP and changes with game updates. citeturn0search0turn0search2

Market collection now fetches every page before replacing the previous region snapshot, so orders that disappeared from ESI are removed instead of remaining as stale opportunities. ESI market orders are cached by CCP for five minutes, so the collector should not poll the same region more frequently than useful. citeturn0search9turn0search11

## Next milestones

1. Add character skills/standings profiles for automatic tax and broker-fee presets.
2. Add route safety settings and hauling-risk assumptions.
3. Add station/system names and security status from SDE.
4. Add ISK/hour and capital-turnover ranking after recording execution time/history.
5. Add execution tracking so realized results can be compared with scanner estimates.
