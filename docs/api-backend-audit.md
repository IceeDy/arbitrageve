# Backend Audit and API Design

## 1. Audit scope

The current backend already contains most of the domain logic required for a web API. The main architectural issue is that the Streamlit application calls the domain/database layer directly. The next frontend should consume a stable HTTP API instead of importing SQLAlchemy models or service functions.

### Current backend layers

- **Database:** SQLAlchemy + psycopg, PostgreSQL only.
- **SDE:** items, regions, solar systems and stargates.
- **Market ingestion:** ESI market client and complete regional snapshot replacement.
- **Market worker:** adaptive regional refresh, worker state and health audit.
- **Opportunity engine:** SQL candidate discovery, order-book execution, costs, routes, risk and execution metrics.
- **Execution:** level-by-level order-book simulation and slippage/depth metrics.
- **Risk:** route security classification and configurable route filters.
- **Operational state:** `AppState` stores SDE and worker lifecycle metadata.
- **Current UI coupling:** Streamlit initializes the database and directly calls backend services.

## 2. Important findings

### 2.1 Keep the existing domain logic

Do not duplicate opportunity calculations inside the API or frontend.

The API should call:

- `find_opportunities()`
- `audit_opportunity_execution()`
- `simulate_order_book_execution()`
- `audit_region_refresh()`
- SDE loaders/bootstrap functions where administrative access is explicitly required.

The React frontend should only render API responses and send user parameters.

### 2.2 Opportunity calculation is currently a service operation

`find_opportunities()` already handles:

- source/destination regions;
- capital and cargo constraints;
- minimum ROI/profit;
- order-book depth;
- market freshness;
- route calculation;
- route risk filters;
- execution time;
- ISK/hour;
- capital efficiency;
- diagnostics;
- candidate-lane limits;
- optional type filters.

Therefore the first API should expose this operation rather than introduce a new query implementation.

### 2.3 Market snapshots are region-scoped

`collect_region()` completely replaces a region snapshot only after all ESI pages have been collected. This is important for API semantics: the API should expose snapshot metadata and read operations, while collection itself should remain an operational worker/admin action rather than a frontend request by default.

### 2.4 Market refresh health is already a domain service

`audit_region_refresh()` provides:

- region;
- order count;
- last collection;
- age;
- target refresh interval;
- overdue ratio;
- priority;
- status.

The API should return these fields directly.

### 2.5 SDE and market data are different domains

SDE endpoints should expose static/reference data. Market endpoints should expose dynamic snapshots. Do not combine SDE refresh and market collection into a single endpoint.

## 3. Proposed API structure

Base prefix:

`/api/v1`

The API should be versioned from the beginning so the React frontend can evolve without forcing breaking changes.

### System

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Liveness/readiness and database connectivity |
| GET | `/api/v1/system/status` | Application, SDE, market and worker status |

### Opportunities

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/opportunities/search` | Run the existing opportunity scanner with explicit parameters |
| GET | `/api/v1/opportunities/{opportunity_id}` | Reserved for persisted opportunity snapshots |
| POST | `/api/v1/opportunities/{opportunity_id}/audit` | Re-audit a persisted opportunity |
| POST | `/api/v1/opportunities/simulate` | Explicit order-book execution simulation |

**Important:** the current scanner does not persist opportunities as database entities. Therefore `GET /opportunities/{id}` should not be implemented until opportunity snapshots/history exist. The first frontend can use the search response as an in-memory result.

### Market

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/market/health` | Adaptive refresh audit for all regions |
| GET | `/api/v1/market/regions/{region_id}/snapshot` | Snapshot metadata for one region |
| GET | `/api/v1/market/regions/{region_id}/orders` | Paginated market orders |
| GET | `/api/v1/market/regions/{region_id}/summary` | Aggregated market statistics |
| GET | `/api/v1/market/orders/{order_id}` | Single order lookup |
| POST | `/api/v1/market/regions/{region_id}/collect` | Manual/admin collection trigger |

The manual collection endpoint should not be used by the normal Radar polling loop. The worker remains responsible for scheduled collection.

### SDE

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/sde/items` | Search/list item metadata |
| GET | `/api/v1/sde/items/{type_id}` | Item detail |
| GET | `/api/v1/sde/regions` | List regions |
| GET | `/api/v1/sde/regions/{region_id}` | Region detail |
| GET | `/api/v1/sde/systems` | Search/list solar systems |
| GET | `/api/v1/sde/systems/{system_id}` | System detail |
| GET | `/api/v1/sde/systems/{system_id}/route` | Route lookup using the existing route graph |
| GET | `/api/v1/sde/stargates` | Stargate/graph metadata |
| POST | `/api/v1/sde/refresh` | Administrative SDE refresh |

SDE refresh must be protected as an administrative operation. The public Radar should only read SDE data.

### Worker

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/worker/status` | Current worker lifecycle state |
| GET | `/api/v1/worker/schedule` | Current adaptive region schedule |
| POST | `/api/v1/worker/run` | Administrative/manual worker trigger |

The worker should remain independently executable by GitHub Actions. API-triggered execution should be optional and protected.

## 4. Opportunity search contract

### Request

```json
{
  "source_region_id": 10000002,
  "destination_region_id": 10000043,
  "capital_isk": 100000000,
  "cargo_m3": 400,
  "min_roi": 0.05,
  "min_profit_isk": 100000,
  "limit": 100,
  "sort_by": "net_profit",
  "max_candidate_lanes": 4,
  "max_market_age_minutes": 60,
  "route_preference": "Shorter",
  "security_penalty": 50,
  "risk": {
    "allow_highsec": true,
    "allow_lowsec": false,
    "allow_nullsec": false,
    "max_jumps": 30
  },
  "execution": {
    "fixed_minutes": 10,
    "minutes_per_jump": 2,
    "return_trip": false
  },
  "type_ids": []
}
```

### Response

The API should preserve the existing opportunity fields instead of inventing a second business model.

Important response groups:

- identity: `type_id`, `name`
- lane: source/destination region, system and location
- quantity/capacity: quantity, volume, cargo usage, capital required
- economics: buy cost, sell revenue, gross/net profit, taxes, broker fee, transport, safety margin
- profitability: ROI, capital efficiency, profit per unit, ISK/hour
- execution: average prices, top prices, slippage, levels used, book coverage
- route: route systems, jumps, security classification and risk
- freshness: collection timestamp/market age
- operational classification: execution/liquidity class
- diagnostics/audit fields where explicitly requested.

The API must not recompute these values in TypeScript.

## 5. Pagination and large market data

Market orders can become very large. Never return an entire region's order book in one response.

Use cursor or page pagination:

`GET /api/v1/market/regions/{region_id}/orders?type_id=34&side=sell&page_size=100&cursor=...`

Default page size should be conservative, with a hard maximum.

For the Radar, prefer aggregated endpoints and opportunity search. Raw orders are an inspection/debugging capability, not the primary UI data source.

## 6. Error model

All API errors should use one JSON shape:

```json
{
  "error": {
    "code": "MARKET_SNAPSHOT_STALE",
    "message": "The requested market snapshot is older than the configured limit.",
    "details": {}
  }
}
```

Suggested codes:

- `DATABASE_UNAVAILABLE`
- `SDE_INCOMPLETE`
- `MARKET_EMPTY`
- `MARKET_SNAPSHOT_STALE`
- `INVALID_PARAMETER`
- `ROUTE_UNAVAILABLE`
- `OPPORTUNITY_NOT_EXECUTABLE`
- `COLLECTION_IN_PROGRESS`
- `ADMIN_REQUIRED`

## 7. API implementation plan

### Phase 1 — API foundation

Create:

```
api/
  __init__.py
  main.py
  dependencies.py
  errors.py
  schemas/
  routers/
```

Add FastAPI and Pydantic schemas without moving the existing domain code.

### Phase 2 — read-only operational API

Implement first:

1. `GET /health`
2. `GET /system/status`
3. `GET /market/health`
4. `GET /sde/regions`
5. `GET /sde/systems`
6. `GET /sde/items`
7. `POST /opportunities/search`

These endpoints provide enough functionality to build the first React Radar.

### Phase 3 — detailed market API

Add:

- region snapshot metadata;
- paginated orders;
- item/order lookups;
- route details.

### Phase 4 — administrative API

Add protected:

- SDE refresh;
- manual market collection;
- worker trigger.

### Phase 5 — persistence/history

Add database entities for:

- opportunity snapshots;
- scanner runs;
- execution history.

Only then implement opportunity IDs and historical endpoints.

## 8. Frontend boundary

React must not:

- import Python code;
- know SQLAlchemy models;
- calculate ROI;
- calculate ISK/hour;
- reconstruct order-book execution;
- calculate route risk;
- connect directly to PostgreSQL.

React should send scanner parameters and render the API's domain result.

This keeps the business rules in one place and allows the existing backend, API and future clients to share the same calculations.

## 9. First API milestone

The first implementation milestone should be a **read-only API plus opportunity search**, not a full CRUD API.

Target dependency addition:

- `fastapi`
- `uvicorn[standard]`

No database model changes are required for this milestone.

The existing Streamlit UI can remain operational during migration. Once the React Radar consumes these endpoints successfully, Streamlit can be retired.
